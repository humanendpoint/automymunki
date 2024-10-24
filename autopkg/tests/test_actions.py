"""
This script is meant to test workflow steps and remediate where it can.
It currently has five main functions:

1. Removes unused recipe repos added to the repo list .txt file

2. Adds missing recipe repos to the repo list .txt file

3. Tests the Munki version used across all workflows, whether we're using the
   latest version or not, against the latest version released on github, and updates
   the env var values in the steps that install Munki.

4. If we have apps in the Munki GCP bucket that are not in any Munki pkgsinfo, it will
   remove them from the bucket.

5. Sends a Slack notification with the changes made.

"""

import json
import hashlib
import os
import re
import requests
import plistlib
import yaml
from google.cloud import storage
from slack_sdk import WebClient

################################################
##################   CODE  #####################

#### Variable stuff

# gcp bucket name
gcp_bucket = os.environ.get("GCP_BUCKET")
# Directory containing the pkgsinfo files
pkgsinfo_dir = os.environ.get("PKGSINFO_DIR")
# Define path to start searching for .munki.recipe(.yaml) files
overrides_folder = os.environ.get("OVERRIDES_FOLDER")
# Munki repository directory
munki_repo_dir = os.environ.get("MUNKI_REPO_DIR")
# Directory containing the workflow YAML files
workflow_dir = os.environ.get("WORKFLOW_FOLDER")
# GitHub token for API requests
github_token = os.environ.get("GITHUB_TOKEN")
# Path to .txt file with repo names
repo_list_path = os.environ.get("REPO_LIST")


#### Recipe stuff


def extract_repo_from_path(path):
    if "com.github.autopkg" in path:
        # Extract everything after "com.github.autopkg." but before the next "/"
        repo_name_match = re.search(r"com\.github\.autopkg\.([a-zA-Z0-9.-]+)", path)
        if repo_name_match:
            return repo_name_match.group(1)
    return ""


def extract_reponame_from_recipes(file_path):
    """Extract repo names from Munki recipes."""
    try:
        with open(file_path, "rb") as plist_file:
            plist_data = plistlib.load(plist_file)

            repo_names = set()
            # Check for 'parent_recipes' in 'ParentRecipeTrustInfo'
            parent_recipe_info = plist_data.get("ParentRecipeTrustInfo", {}).get(
                "parent_recipes", {}
            )
            for recipe_info in parent_recipe_info.values():
                repo_name = extract_repo_from_path(recipe_info.get("path", ""))
                if repo_name:
                    repo_names.add(repo_name)
            # Check for 'non_core_processors' in 'ParentRecipeTrustInfo'
            non_core_processors = plist_data.get("ParentRecipeTrustInfo", {}).get(
                "non_core_processors", {}
            )
            for processor_info in non_core_processors.values():
                repo_name = extract_repo_from_path(processor_info.get("path", ""))
                if repo_name:
                    repo_names.add(repo_name)

            return list(repo_names)

    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return []


def extract_reponame_from_yaml(file_path):
    """Extract repo names from YAML files."""
    try:
        with open(file_path, "r") as yaml_file:
            yaml_data = yaml.safe_load(yaml_file)

            repo_names = set()
            # Check for 'parent_recipes' in 'ParentRecipeTrustInfo'
            parent_recipes = yaml_data.get("ParentRecipeTrustInfo", {}).get(
                "parent_recipes", {}
            )
            for recipe_info in parent_recipes.values():
                repo_name = extract_repo_from_path(recipe_info.get("path", ""))
                if repo_name:
                    repo_names.add(repo_name)
            # Check for 'non_core_processors'
            non_core_processors = yaml_data.get("ParentRecipeTrustInfo", {}).get(
                "non_core_processors", {}
            )
            for processor_info in non_core_processors.values():
                repo_name = extract_repo_from_path(processor_info.get("path", ""))
                if repo_name:
                    repo_names.add(repo_name)

            return list(repo_names)

    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return []


def search_for_identifiers(folders_to_check):
    """Search for Munki recipe and YAML identifiers."""
    identifiers = set()

    for folder in folders_to_check:
        for root, _, files in os.walk(folder):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                if file_name.endswith(".munki.recipe"):
                    identifiers.update(extract_reponame_from_recipes(file_path))
                elif file_name.endswith("munki.recipe.yaml"):
                    identifiers.update(extract_reponame_from_yaml(file_path))

    return identifiers


#### YAML stuff


def update_yaml(yaml_path, new_sha256, new_url):
    """Update the YAML workflow with new values."""
    with open(yaml_path, "r") as file:
        yaml_text = file.read()

    # Update the YAML workflow with new values.
    # Why I do it this way is because any yaml lib was being difficult.
    updated_yaml = re.sub(
        r'MUNKI_SHA256: ".+"', f'MUNKI_SHA256: "{new_sha256}"', yaml_text
    )

    updated_yaml = re.sub(r'MUNKI_URL: ".+"', f'MUNKI_URL: "{new_url}"', updated_yaml)

    with open(yaml_path, "w") as file:
        file.write(updated_yaml)


#### GCP bucket things


def list_gcp_bucket_files(bucket_name):
    """List all files in the GCP bucket."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blobs = bucket.list_blobs()
    return {
        os.path.basename(blob.name)
        for blob in blobs
        if blob.name.endswith((".pkg", ".dmg"))
    }


def list_munki_pkginfo_files(pkgsinfo_dir):
    """List all package names from Munki's pkgsinfo directory."""
    munki_packages = set()

    for root, dirs, files in os.walk(pkgsinfo_dir):
        for file_name in files:
            if file_name.endswith(".plist"):
                plist_path = os.path.join(root, file_name)
                try:
                    with open(plist_path, "rb") as plist_file:
                        plist_data = plistlib.load(plist_file)
                        # Retrieve the installer item location
                        installer_item_location = plist_data.get(
                            "installer_item_location"
                        )
                        if installer_item_location:
                            # Split the path and extract the package name
                            # The package name is the last part of the path
                            package_name = installer_item_location.split("/")[
                                -1
                            ]  # Get the last part
                            munki_packages.add(package_name)
                except Exception as e:
                    print(f"Error parsing {plist_path}: {e}")

    return munki_packages


def find_superfluous_packages(pkgsinfo_dir, gcp_bucket):
    """Find packages in the GCP bucket that are not in any Munki manifests."""
    # List packages in the GCP bucket
    gcp_packages = list_gcp_bucket_files(gcp_bucket)
    # List packages from Munki's pkgsinfo
    munki_packages = list_munki_pkginfo_files(pkgsinfo_dir)
    # Find packages in GCP that are not in Munki
    orphaned_packages = gcp_packages - munki_packages
    return list(orphaned_packages)


#### Repo and identifiers stuff


def update_repo_list(repo_name, repo_list_path, edits):
    """Update the repo .txt file with missing repos."""
    try:
        # Handle special case for the "dataJAR-recipes" repo
        if "datajar" in repo_name:
            repo_name = "dataJAR-recipes"

        with open(repo_list_path, "r") as repo_file:
            repo_list = repo_file.read().splitlines()
        # Check if the repo is already in the list
        if repo_name not in repo_list:
            # Add a heading for added repos if this is the first addition
            if not any("Added repos" in edit for edit in edits):
                edits.append("*Added repos to repo file*:")

            with open(repo_list_path, "a") as repo_file:
                repo_file.write(f"{repo_name}\n")

            edits.append(f"{repo_name}")
            return True
        return False
    except Exception as e:
        print(f"Error updating the .txt repo file: {e}")


def remove_unused_repos(repo_list_path, used_repos, edits):
    """Remove unused repos from the repo .txt file."""
    try:
        with open(repo_list_path, "r") as repo_file:
            repo_list = repo_file.read().splitlines()
        unused_repos = set(repo_list) - set(used_repos)
        if unused_repos:
            updated_repos = [repo for repo in repo_list if repo not in unused_repos]
            edits.append("*Removed unused repos from repo file*:")
            with open(repo_list_path, "w") as repo_file:
                repo_file.write("\n".join(updated_repos) + "\n")

            for repo in unused_repos:
                edits.append(f"{repo}")
        return edits
    except Exception as e:
        print(f"Error cleaning repo_list.txt: {e}")


#### Munki stuff


def url_sha_edit(yaml_file_path, github_token):
    """Edit the Munki download URL and SHA256 checksum in the workflow file."""
    # GitHub repository and release URL
    repository = "munki/munki"
    release_url = "https://api.github.com/repos/{}/releases/latest".format(repository)

    # Better print output. Remove everything before and
    # including the last slash.
    last_slash_index = yaml_file_path.rfind("/")
    yaml_filename = yaml_file_path[last_slash_index + 1 :]

    edit_status = ""

    try:
        # Get the latest release information
        headers = {}
        headers["Authorization"] = f"token {github_token}"
        response = requests.get(release_url, headers=headers)
        response.raise_for_status()
        data = json.loads(response.text)

        if "message" in data and data["message"] == "Not Found":
            print("GitHub repository not found.")
            return

        # Extract the latest release information
        assets = data.get("assets", [])

        # Find the .pkg asset
        pkg_asset = None
        for asset in assets:
            if asset["name"].endswith(".pkg"):
                pkg_asset = asset
                break
        # If we find an asset matching .pkg
        if pkg_asset is not None:
            # Get the SHA256 checksum of the .pkg asset
            pkg_url = pkg_asset["browser_download_url"]
            pkg_response = requests.get(pkg_url)
            pkg_response.raise_for_status()
            pkg_sha256 = hashlib.sha256(pkg_response.content).hexdigest()

            with open(yaml_file_path, "r") as file:
                yaml_text = file.read()
            # Extract the current values from the workflow file
            current_sha256 = re.search(r"MUNKI_SHA256: \"([^\"]+)\"", yaml_text)
            current_url = re.search(r"MUNKI_URL: \"([^\"]+)\"", yaml_text)
            # These two exist in the workflow files we want to update
            if current_sha256 and current_url:
                current_sha256 = current_sha256.group(1)
                current_url = current_url.group(1)
                # Compare the calculated SHA256 with the current value
                if pkg_sha256 != current_sha256:
                    print(
                        f"{yaml_filename}: SHA256 checksums do not match. Updating YAML file..."
                    )
                    # Update the YAML file
                    update_yaml(yaml_file_path, pkg_sha256, pkg_url)
                    edit_status = (
                        f"{yaml_filename}: updated with new checksum and URL.\n"
                    )
                else:
                    print(f"{yaml_filename}: SHA256 checksums and download URL match.")
            else:
                print(f"{yaml_filename}: Not applicable.")
        else:
            edit_status = "No .pkg asset found in the latest release.\n"
    except requests.RequestException as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")

    return edit_status


# Function to parse Munki manifest files and extract item names
# here for historical purposes cause it's nice
def parse_manifest(manifest_path):
    items = []
    with open(manifest_path, "rb") as file:
        try:
            plist_data = plistlib.load(file)
            if "managed_installs" in plist_data:
                items.extend(plist_data["managed_installs"])
            if "optional_installs" in plist_data:
                items.extend(plist_data["optional_installs"])
        except Exception as e:
            print(f"Error parsing {manifest_path}: {e}")
    return items


def send_slack_notif(orphans, edits):
    client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
    blocks = []

    if orphans:
        orphan_text = "\n".join(orphans)
        orphan_text += "\n\n"

        orphan_blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": orphan_text,
                },
            }
        ]
        blocks.extend(orphan_blocks)

    if edits:
        edits_text = "*Completed tasks:*\n" + "\n".join(edits)
        edits_blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": edits_text,
                },
            }
        ]
        blocks.extend(edits_blocks)

    if blocks:
        response = client.chat_postMessage(
            channel=os.environ["CHANNEL_ID"], blocks=blocks
        )
        return f"Message created: {response}"


def orphans():
    """Check for orphaned packages in the GCP bucket."""
    orphaned_packages = find_superfluous_packages(pkgsinfo_dir, gcp_bucket)
    print(f"orphaned packages: {len(orphaned_packages)}")
    orphaned_message = []
    if orphaned_packages:
        orphaned_message.append("*Munki files removed from GCP bucket*:*")
        if len(orphaned_packages) == 1:
            # Only one orphaned app, no need for a comma and space
            orphaned_message.append(orphaned_packages[0])
        else:
            # Multiple orphaned apps, list with comma and space
            orphaned_message.extend(orphaned_packages)

    return orphaned_message


def edits_made():
    """
    Check for edits to be made in github workflow and repo list .txt files
    and send a Slack notification of changes made.
    """
    # List of edits to be made and sen
    edits = []
    folders_to_check = [overrides_folder]
    # instead of looking for e.g. repo folder in the cache folder,
    # we check the recipes in the override folder and their keys for
    # the correct repo names.
    repo_identifiers = search_for_identifiers(folders_to_check)
    # Extract
    used_repos = set(
        identifier[1] for identifier in repo_identifiers
    )  # Only keep the repo names
    print(f"used repos: {len(used_repos)}")
    # Update repo_list.txt with missing repos
    for repo in used_repos:
        # test if we need to update the repo list
        update_repo_list(repo, repo_list_path, edits)
    # Remove unused repos from repo_list.txt
    edits = remove_unused_repos(repo_list_path, used_repos, edits)
    # Process other workflows in the workflow dir
    all_yaml_files = [f for f in os.listdir(workflow_dir) if f.endswith(".yml")]
    for yaml_file in all_yaml_files:
        yaml_file_path = os.path.join(workflow_dir, yaml_file)
        munki_edit = url_sha_edit(yaml_file_path, github_token)
        if munki_edit:
            edits.append(munki_edit)

    print(f"edits: {len(edits)}")

    return edits


def main():
    edits = edits_made()
    orphaned_message = orphans()
    if orphaned_message or edits:
        slack_status = send_slack_notif(orphaned_message, edits)
        print(slack_status)
        # human intervention is then here required.
        # to automate this we may be taking too many assumptions, but there are ways to do it.
        # for example, we could have a slack message with a button that triggers the next step, or
        # we could also have a scheduled action that runs this script again after a certain amount of time.


if __name__ == "__main__":
    main()
