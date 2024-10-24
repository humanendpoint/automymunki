# automaticmunki

This is a baseline for a fully automatic Munki repo, built upon from an old version of ADA Health's AutoPkg repo. <br>

## About


- Run autopkg and populate the `munki_repo` folder with pkginfo files
  - supports shipping packages to a GCP bucket
  - we also upload an artifact with the json results from each app cache
- Cleanup the repo (and bucket) keeping a standard `2` versions for each app/pkginfo pair
  - also tests the Munki versions used in workflows and updates SHA256 and URL env vars if necessary 
- Keep Munki manifests updated depending on information fed to the github workflow
  - there are workflows and scripts to add/edit/remove manifests in the repo
  - output to Slack
- Generate an automatic wiki depending on the processors and scripts in the repo
  - searches for all `.py/.sh` scripts and includes each docstring
  - counts overrides and pkginfo files
- And more!

It is meant to explore this repo and learn how it works before using it, but I've included a few hints below.

## How to use

There's plenty of wiggle room to customize this further, but there are a few things necessary to really benefit from this:
- Okta as IdP: to send enrolling information to the workflow API endpoint for `manifest-handling.yml`. Handling this is currently out of scope of the goal of this repo, but the code is written to adhere to Okta's API and how it sends payloads.
- a development platform: such as GCP and a bucket to ship the packages to. There's also a separate `clean-repo.yml` workflow to cleanup that same bucket, which is also why GCP is mostly required until I have rewritten this to support both.

### Secrets needed

#### General
- `GIT_APP_PEM_KEY`
- `GIT_APP_ID`

#### Munki manifests
- `OKTA_API_TOKEN`
- `OKTA_DOMAIN`
  
#### For Slack
- `SLACK_WEBHOOK`
- `CHANNEL_ID`
- `BOT_ID`

#### For GCP
- `GCP_CREDENTIALS`
