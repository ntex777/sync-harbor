# sync-harbor

This script syncs artifacts using [skopeo](https://github.com/containers/skopeo) to push blobs between registries

This was created to gap the need of copying artifacts in certain order.
If you have policies based on number of artifacts of days, timestamp push will be important, so this script loops on all projects and repositories and order by Push timestamp ASC and Pushes to the remote registry on same order. :)

Just install skopeo and python and you will be good to go.

NOTE: First version was docker pull / tag / push to the localhost, that was cumbersome and would take too long to sync repos.
