import os
import sys
import requests
from requests.auth import HTTPBasicAuth
import warnings
from requests.packages.urllib3.exceptions import InsecureRequestWarning
import urllib.parse

# Suppress SSL warnings
warnings.simplefilter('ignore', InsecureRequestWarning)
# Harbor FQDN
OLD_HARBOR_URL = "goharbor.contoso.org"
NEW_HARBOR_URL = "goharbor-new.contoso.org"

# Harbor API credentials
USERNAME = "username"
PASSWORD = "secretpassword"

# Set environment variables for proxies
os.environ['http_proxy'] = 'http://proxy.contoso.org:8080'
os.environ['https_proxy'] = 'http://proxy.contoso.org:8080'
os.environ['no_proxy'] = 'goharbor.contoso.org, goharbor-new.contoso.org'

def encode_repo_name(repo_name):
    """Encode repository name while preserving slashes."""
    return '/'.join(urllib.parse.quote(part) for part in repo_name.split('/'))

def get_projects(harbor_url):
    """Fetch all projects from Harbor with pagination."""
    all_projects = []
    page = 1
    page_size = 100

    while True:
        url = f"https://{harbor_url}/api/v2.0/projects?page={page}&page_size={page_size}"
        response = requests.get(url, auth=HTTPBasicAuth(USERNAME, PASSWORD), verify=False)

        if response.status_code == 200:
            projects = response.json()
            if not projects:  # No more projects
                break
            all_projects.extend(projects)
            print(f"Fetched {len(projects)} projects from page {page}")

            # If we got fewer than page_size, we're done
            if len(projects) < page_size:
                break
            page += 1
        else:
            print(f"Error fetching projects page {page}: {response.text}")
            break

    print(f"Total projects fetched: {len(all_projects)}")
    return all_projects

def find_repo_project(harbor_url, repo_name):
    projects = get_projects(harbor_url)
    print(f"Checking {len(projects)} projects for repo {repo_name}: {[p['name'] for p in projects]}")
    for project in projects:
        project_name = project['name']
        url = f"https://{harbor_url}/api/v2.0/projects/{project_name}/repositories/{encode_repo_name(repo_name)}"
        print(f"Trying URL: {url}")
        response = requests.get(url, auth=HTTPBasicAuth(USERNAME, PASSWORD), verify=False)
        if response.status_code == 200:
            print(f"Found repo in project: {project_name}")
            return project_name
        else:
            print(f"Not found in project {project_name}: {response.status_code}")
    return None

def get_repositories(harbor_url, project_name):
    """Fetch all repositories from a project with pagination."""
    all_repos = []
    page = 1
    page_size = 100

    while True:
        url = f"https://{harbor_url}/api/v2.0/projects/{project_name}/repositories?page={page}&page_size={page_size}"
        response = requests.get(url, auth=HTTPBasicAuth(USERNAME, PASSWORD), verify=False)

        if response.status_code == 200:
            repos = response.json()
            if not repos:  # No more repos
                break
            all_repos.extend(repos)
            print(f"Fetched {len(repos)} repositories from project {project_name}, page {page}")

            # If we got fewer than page_size, we're done
            if len(repos) < page_size:
                break
            page += 1
        else:
            print(f"Error fetching repositories for project {project_name}, page {page}: {response.text}")
            break

    print(f"Total repositories in project {project_name}: {len(all_repos)}")
    for repo in all_repos:
        print(f" - {repo['name']}")
    return all_repos

def get_all_repositories(harbor_url):
    """Get all repositories from all projects."""
    all_repos = []
    projects = get_projects(harbor_url)

    for project in projects:
        project_name = project['name']
        repos = get_repositories(harbor_url, project_name)
        for repo in repos:
            # Extract just the repo name part (remove project prefix)
            repo_name = repo['name']
            if repo_name.startswith(f"{project_name}/"):
                repo_name = repo_name[len(f"{project_name}/"):]
            all_repos.append(repo_name)

    return all_repos

def get_repo_metadata(harbor_url, project_name, repo_name):
    """Fetch repository metadata with pagination for artifacts."""
    encoded_repo_name = encode_repo_name(repo_name)
    all_artifacts = []
    page = 1
    page_size = 100

    while True:
        url = f"https://{harbor_url}/api/v2.0/projects/{project_name}/repositories/{encoded_repo_name}/artifacts?page={page}&page_size={page_size}"
        print(f"Fetching artifacts from: {url}")
        response = requests.get(url, auth=HTTPBasicAuth(USERNAME, PASSWORD), verify=False)

        if response.status_code == 200:
            artifacts = response.json()
            if not artifacts:  # No more artifacts
                break
            all_artifacts.extend(artifacts)
            print(f"Fetched {len(artifacts)} artifacts from page {page}")

            # If we got fewer than page_size, we're done
            if len(artifacts) < page_size:
                break
            page += 1
        else:
            print(f"Error fetching repository metadata for {repo_name}, page {page}: {response.text}")
            break

    print(f"Total artifacts fetched for {repo_name}: {len(all_artifacts)}")
    return all_artifacts

def sort_artifacts_by_time(artifacts):
    """Sort artifacts by creation time."""
    return sorted(artifacts, key=lambda artifact: artifact.get('push_time', ''))

def image_exists(harbor_url, project_name, repo_name, tag):
    """Check if an image with the specific tag exists in the registry."""
    encoded_repo_name = encode_repo_name(repo_name)
    url = f"https://{harbor_url}/api/v2.0/projects/{project_name}/repositories/{encoded_repo_name}/artifacts/{tag}"
    response = requests.get(url, auth=HTTPBasicAuth(USERNAME, PASSWORD), verify=False)
    return response.status_code == 200

def skopeo_copy(old_image, new_image, old_creds, new_creds):
    """Copy image from old to new Harbor using skopeo."""
    cmd = (
        f"skopeo copy "
        f"--src-creds={old_creds} "
        f"--dest-creds={new_creds} "
        f"--src-tls-verify=false --dest-tls-verify=false "
        f"--all "
        f"docker://{old_image} "
        f"docker://{new_image}"
    )
    print(f"Running: {cmd}")
    return os.system(cmd)

def migrate_repo(old_harbor_url, new_harbor_url, project_name, repo_name, sorted_artifacts):
    print(f"Migration plan for {repo_name} in project {project_name}:")

    # Make sure repo_name uses slashes and is lowercase
    repo_name_for_skopeo = repo_name.replace('%2F', '/').lower()

    for artifact in sorted_artifacts:
        if 'tags' not in artifact or not artifact['tags']:
            print(f"Skipping artifact without tags: {artifact}")
            continue

        tag = artifact['tags'][0]['name']
        old_image = f"{old_harbor_url}/{project_name}/{repo_name_for_skopeo}:{tag}"
        new_image = f"{new_harbor_url}/{project_name}/{repo_name_for_skopeo}:{tag}"

        if image_exists(new_harbor_url, project_name, repo_name, tag):
            print(f"Image {new_image} already exists in the new registry. Skipping...")
            continue

        result = skopeo_copy(
            old_image,
            new_image,
            f"{USERNAME}:{PASSWORD}",
            f"{USERNAME}:{PASSWORD}"
        )

        if result == 0:
            print(f"Successfully migrated {old_image} -> {new_image}")
        else:
            print(f"Failed to migrate {old_image} -> {new_image}")

def process_repository(repo_name):
    """Process a single repository for migration."""
    print(f"\n{'='*60}")
    print(f"Processing repository: {repo_name}")
    print(f"{'='*60}")

    # URL encode the repo name for API calls
    encoded_repo_name = repo_name.replace('/', '%2F')

    print(f"Searching for repository: {encoded_repo_name}")
    project_name = find_repo_project(OLD_HARBOR_URL, encoded_repo_name)

    if project_name:
        print(f"Repository found in project: {project_name}")
        artifacts = get_repo_metadata(OLD_HARBOR_URL, project_name, encoded_repo_name)

        if artifacts:
            sorted_artifacts = sort_artifacts_by_time(artifacts)
            migrate_repo(OLD_HARBOR_URL, NEW_HARBOR_URL, project_name, encoded_repo_name, sorted_artifacts)
        else:
            print(f"No artifacts found in repository: {repo_name}")
    else:
        print(f"Repository not found in any project: {repo_name}")

def main():
    # Check command line arguments
    if len(sys.argv) > 1:
        # Process specific repositories passed as arguments
        repo_names = sys.argv[1:]
        print(f"Processing {len(repo_names)} specified repositories:")
        for repo_name in repo_names:
            process_repository(repo_name)
    else:
        # Process all repositories
        print("No specific repositories specified. Processing all repositories...")
        all_repos = get_all_repositories(OLD_HARBOR_URL)
        print(f"Found {len(all_repos)} repositories total")

        for repo_name in all_repos:
            process_repository(repo_name)

if __name__ == "__main__":
    main()
