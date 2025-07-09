import os
import requests
from requests.auth import HTTPBasicAuth
import warnings
from requests.packages.urllib3.exceptions import InsecureRequestWarning
import urllib.parse

# Suppress SSL warnings, if you don't have CA's installed
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

def get_repositories(harbor_url, project_name):
    """Fetch all repositories in a specific project, handling pagination."""
    repositories = []
    page = 1
    page_size = 100  # Adjust this based on API limitations or requirements

    while True:
        url = f"https://{harbor_url}/api/v2.0/projects/{project_name}/repositories?page={page}&page_size={page_size}"
        response = requests.get(url, auth=HTTPBasicAuth(USERNAME, PASSWORD), verify=False)

        if response.status_code == 200:
            data = response.json()
            if not data:
                break  # Exit loop if no more repositories are returned
            repositories.extend(data)
            page += 1
        else:
            print(f"Error fetching repositories: {response.text}")
            break

    return repositories

def get_repo_metadata(harbor_url, project_name, repo_name):
    """Fetch repository metadata, handling names with multiple slashes."""
    # Remove project name from the beginning of repo_name if present
    if repo_name.startswith(f"{project_name}/"):
        repo_name = repo_name[len(project_name)+1:]

    encoded_repo_name = encode_repo_name(repo_name)

    url = f"https://{harbor_url}/api/v2.0/projects/{project_name}/repositories/{encoded_repo_name}/artifacts"
    print(f"Fetching metadata from: {url}")
    response = requests.get(url, auth=HTTPBasicAuth(USERNAME, PASSWORD), verify=False)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching repository metadata for {repo_name}: {response.text}")
        return []

def sort_repos_by_time(repos):
    """Sort repositories by last update time."""
    return sorted(repos, key=lambda repo: repo.get('update_time', ''), reverse=True)

def sort_artifacts_by_time(artifacts):
    """Sort artifacts by creation time."""
    return sorted(artifacts, key=lambda artifact: artifact.get('push_time', ''))

def image_exists(harbor_url, project_name, repo_name, tag):
    """Check if an image with the specific tag exists in the registry."""
    encoded_repo_name = encode_repo_name(repo_name)
    url = f"https://{harbor_url}/api/v2.0/projects/{project_name}/repositories/{encoded_repo_name}/artifacts/{tag}"
    response = requests.get(url, auth=HTTPBasicAuth(USERNAME, PASSWORD), verify=False)
    return response.status_code == 200

def migrate_repo(old_harbor_url, new_harbor_url, project_name, repo_name, sorted_artifacts):
    """Migrate repository if it doesn't exist in the new registry, then delete local images."""
    print(f"Migration plan for {repo_name} in project {project_name}:")
    for artifact in sorted_artifacts:
        tag = artifact['tags'][0]['name']

        # Ensure repo_name doesn't start with project_name
        if repo_name.startswith(f"{project_name}/"):
            repo_name = repo_name[len(project_name)+1:]

        old_image = f"{old_harbor_url}/{project_name}/{repo_name}:{tag}"
        new_image = f"{new_harbor_url}/{project_name}/{repo_name}:{tag}"

        if image_exists(new_harbor_url, project_name, repo_name, tag):
            print(f"Image {new_image} already exists in the new registry. Skipping...")
            continue

        pull_cmd = f"docker pull {old_image}"
        print(f"Executing: {pull_cmd}")
        pull_status = os.system(pull_cmd)

        if pull_status == 0:
            tag_cmd = f"docker tag {old_image} {new_image}"
            push_cmd = f"docker push {new_image}"

            print(f"Tagging: {tag_cmd}")
            os.system(tag_cmd)

            print(f"Pushing: {push_cmd}")
            push_status = os.system(push_cmd)

            if push_status == 0:
                print("Push successful. Deleting local images...")
                delete_old_cmd = f"docker rmi {old_image}"
                delete_new_cmd = f"docker rmi {new_image}"

                print(f"Deleting old image: {delete_old_cmd}")
                os.system(delete_old_cmd)

                print(f"Deleting new image: {delete_new_cmd}")
                os.system(delete_new_cmd)
            else:
                print(f"Failed to push {new_image}")
        else:
            print(f"Failed to pull repository: {old_image}")

def main():
    project_name = "library"  # Change this to the project you want to migrate

    repos = get_repositories(OLD_HARBOR_URL, project_name)
    repos = sort_repos_by_time(repos)  # Sort repositories by last update time

    if repos:
        for repo in repos:
            repo_name = repo['name']
            print(f"Processing repository: {repo_name}")

            artifacts = get_repo_metadata(OLD_HARBOR_URL, project_name, repo_name)

            if artifacts:
                sorted_artifacts = sort_artifacts_by_time(artifacts)
                migrate_repo(OLD_HARBOR_URL, NEW_HARBOR_URL, project_name, repo_name, sorted_artifacts)
            else:
                print(f"No artifacts found in repository: {repo_name}")
    else:
        print(f"No repositories found in project: {project_name}")

if __name__ == "__main__":
    main()
