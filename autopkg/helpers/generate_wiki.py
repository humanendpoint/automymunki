"""
Created to help organize scripts and their description.
This populates the Munki wiki page with the contents of every script's description.

Currently looks for .sh/.py scripts and the first pythonic comment block,
then categorizes them. You can see this on the Munki wiki page, depending on what they're used as.
It also removes pages from the wiki that does not have a corresponding script in the repo.

Improvements needed, mainly shell related:
- A proper check for shell style commenting
- A proper check for docstrings, currently acts weird with some shell comments
"""

import os
import re
import requests
import subprocess
import shutil
import sys


def categorize_scripts(repo_directory):
    processor_scripts = {}
    regular_scripts = {}
    test_scripts = {}
    munki_scripts = {}

    for root, _, files in os.walk(repo_directory):
        for file in files:
            if file.endswith((".sh", ".py")):
                file_path = os.path.join(root, file)
                with open(file_path, "r") as f:
                    lines = f.read()
                    description = extract_description(lines)
                    if description:
                        if "processors" in file_path or "autopkg_tools" in file_path:
                            processor_scripts[file] = description
                        elif "test" in file_path or "local_tools" in file_path:
                            test_scripts[file] = description
                        elif (
                            "promoter" in file_path
                            or "MunkiCatalog" in file_path
                            or "manifest" in file_path
                            or "application" in file_path
                        ):
                            munki_scripts[file] = description
                        else:
                            regular_scripts[file] = description

    return processor_scripts, regular_scripts, test_scripts, munki_scripts


def extract_description(script_content):
    start = script_content.find('"""')
    end = script_content.find('"""', start + 3)
    if start != -1 and end != -1:
        return script_content[start : end + 3].strip('"\n ')
    return ""


def generate_markdown(description):
    output = f"# Description\n\n{description}\n"
    return output


def update_sidebar(
    sidebar_path, processor_info, regular_info, test_scripts, munki_scripts
):
    with open(sidebar_path, "r") as fdesc:
        sidebar_content = fdesc.read()

    # wiki sidebar entries
    new_sidebar = sidebar_content
    new_sidebar += "\n- Information\n"
    new_sidebar += "  - [[Munki]]\n"
    new_sidebar += "\n- Script Reference\n"
    new_sidebar += "  - AutoPkg Related\n"

    for script_name in processor_info:
        new_sidebar += f"    - [[{os.path.splitext(script_name)[0]}]]\n"

    new_sidebar += "  - Munki\n"

    for script_name in munki_scripts:
        new_sidebar += f"    - [[{os.path.splitext(script_name)[0]}]]\n"

    new_sidebar += "  - Helpers\n"

    for script_name in regular_info:
        new_sidebar += f"    - [[{os.path.splitext(script_name)[0]}]]\n"

    new_sidebar += "  - Testers\n"

    for script_name in test_scripts:
        new_sidebar += f"    - [[{os.path.splitext(script_name)[0]}]]\n"

    with open(sidebar_path, "w") as fdesc:
        fdesc.write(new_sidebar)


def count_manifests(manifests_path):
    # Get the list of items in the "manifests" directory, excluding the "groups" folder
    manifest_items = [item for item in os.listdir(manifests_path) if item != "groups"]
    num_manifests = len(manifest_items)
    return num_manifests


def gather_munki_info(workspace_directory, folder_path):
    # count the number of things in specific folders
    folder_full_path = os.path.join(workspace_directory, folder_path)
    folder_files = os.listdir(folder_full_path)
    num_files = len(folder_files)
    manifests_path = os.path.join(workspace_directory, "munki_repo", "manifests")
    num_manifests = count_manifests(manifests_path)
    apps_path = os.path.join(workspace_directory, "munki_repo", "pkgsinfo", "apps")
    apps = os.listdir(apps_path)
    num_apps = len(apps)

    # construct the link to the Munki repository
    munki_repo_link = "https://github.com/munki/munki"

    # fetch release information from the Munki repository
    releases_url = "https://api.github.com/repos/munki/munki/releases/latest"
    headers = {"Authorization": f'token {os.environ.get("GITHUB_TOKEN")}'}
    try:
        response = requests.get(releases_url, headers=headers)
        response.raise_for_status()
        release_data = response.json()
        latest_release_tag = release_data["tag_name"]
        release_notes_raw = release_data.get("body", "No release notes available.")
        matches = re.findall(
            r"#{2,}\s(Fixes|Other changes|Enhancements|Improvements|New features and improvements|New features)(.*?)(?=#{2,}|$)",
            release_notes_raw,
            re.DOTALL,
        )
        formatted_release_notes = []
        fixes_section = None
        other_changes_section = None
        enhancements_section = None
        improvements_section = None
        features_and_improvements_section = None
        new_features_section = None

        for section, content in matches:
            if section == "Fixes":
                fixes_section = content
            elif section == "Other changes":
                other_changes_section = content
            elif section == "Enhancements":
                enhancements_section = content
            elif section == "Improvements":
                improvements_section = content
            elif section == "New features and improvements":
                features_and_improvements_section = content
            elif section == "New features in version":
                new_features_section = content

        # check if sections are present and output them
        if fixes_section:
            formatted_release_notes.append(f"Fixes:\n{fixes_section}")

        if other_changes_section:
            formatted_release_notes.append(f"Other changes:\n{other_changes_section}")

        if enhancements_section:
            formatted_release_notes.append(f"Enhancements:\n{enhancements_section}")

        if improvements_section:
            formatted_release_notes.append(f"Improvements:\n{improvements_section}")

        if features_and_improvements_section:
            formatted_release_notes.append(
                f"New features and improvements:\n{features_and_improvements_section}"
            )

        if new_features_section:
            formatted_release_notes.append(
                f"New features in version:\n{new_features_section}"
            )

        release_notes = "\n".join(formatted_release_notes)
        print(f"release notes formatted: {release_notes}")

    except requests.exceptions.RequestException as e:
        latest_release_tag = "Unable to fetch latest release tag"
        release_notes = "Unable to fetch release notes"
        print(f"API Request Error: {e}")

    return (
        latest_release_tag,
        num_files,
        num_manifests,
        num_apps,
        munki_repo_link,
        release_notes,
    )


def get_latest_tag():
    repo_url = f"https://api.github.com/repos/humanendpoint/automaticmunki/tags"
    github_headers = {
        "Content-Type": "application/json",
        "Authorization": f"token {os.environ.get('GITHUB_TOKEN')}",
    }
    try:
        response = requests.get(repo_url, headers=github_headers)
        if response.status_code == 200:
            tags = response.json()
            print(f"tags: {tags}")
            # Ensure tags are not empty
            if len(tags) > 0:
                # The tags are sorted in descending order by default, so the first one is the latest
                latest_tag = tags[0]["name"]
                return latest_tag
            else:
                return None
        else:
            print(f"Failed to retrieve tags. Status code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return None


def main(repo_directory):
    (
        processor_scripts,
        regular_scripts,
        test_scripts,
        munki_scripts,
    ) = categorize_scripts(repo_directory)
    wiki_repo_directory = os.path.join(os.environ["GITHUB_WORKSPACE"], "wiki")
    sidebar_path = os.path.join(wiki_repo_directory, "_Sidebar.md")
    if os.path.exists(sidebar_path):
        os.remove(sidebar_path)

    subprocess.run(["touch", os.path.join(wiki_repo_directory, "_Sidebar.md")])
    # create directories if they don't exist
    for subdir in ["processors", "scripts", "testers", "munki"]:
        subdir_path = os.path.join(wiki_repo_directory, subdir)
        os.makedirs(subdir_path, exist_ok=True)

    # Gather the list of existing wiki pages
    existing_wiki_pages = set()
    for root, _, files in os.walk(wiki_repo_directory):
        for file in files:
            if file.endswith(".md"):
                existing_wiki_pages.add(os.path.splitext(file)[0])

    # Check for wiki pages that no longer have corresponding scripts
    for page_name in existing_wiki_pages:
        if (
            page_name not in processor_scripts
            and page_name not in regular_scripts
            and page_name not in test_scripts
            and page_name not in munki_scripts
        ):
            # Delete the wiki page
            wiki_page_path = os.path.join(
                wiki_repo_directory, "processors", f"{page_name}.md"
            )
            if os.path.exists(wiki_page_path):
                os.remove(wiki_page_path)
            wiki_page_path = os.path.join(
                wiki_repo_directory, "munki", f"{page_name}.md"
            )
            if os.path.exists(wiki_page_path):
                os.remove(wiki_page_path)
            wiki_page_path = os.path.join(
                wiki_repo_directory, "scripts", f"{page_name}.md"
            )
            if os.path.exists(wiki_page_path):
                os.remove(wiki_page_path)
            wiki_page_path = os.path.join(
                wiki_repo_directory, "testers", f"{page_name}.md"
            )
            if os.path.exists(wiki_page_path):
                os.remove(wiki_page_path)

    munki_info = ""
    # gather Munki information
    (
        latest_release_tag,
        num_files,
        num_manifests,
        num_apps,
        munki_repo_link,
        release_notes,
    ) = gather_munki_info(repo_directory, os.path.join("autopkg", "RecipeOverrides"))
    local_latest_release_tag = get_latest_tag()
    release_notes = (
        f"""<br>

# Current Munki version release notes
- Link to real Munki repo is [here]({munki_repo_link}).
<br>

{release_notes}
"""
        if release_notes
        else ""
    )
    # if local and remote release tags match, sort of, add the release notes to the Munki.md page
    munki_info = f"""# Munki Information

- latest public release: {latest_release_tag}

- served apps: {num_apps}

- recipe overrides: {num_files}
<br>

---
{release_notes}
"""

    munki_md_path = os.path.join(wiki_repo_directory, "Munki.md")
    if os.path.exists(munki_md_path):
        os.remove(munki_md_path)

    subprocess.run(["touch", os.path.join(wiki_repo_directory, "Munki.md")])
    with open(munki_md_path, "w") as f:
        f.write(munki_info)

    sidebar_source = os.path.join(repo_directory, "_Sidebar.md")
    sidebar_destination = os.path.join(wiki_repo_directory, "_Sidebar.md")
    shutil.copyfile(sidebar_source, sidebar_destination)

    sidebar_path = os.path.join(wiki_repo_directory, "_Sidebar.md")
    update_sidebar(
        sidebar_path, processor_scripts, regular_scripts, test_scripts, munki_scripts
    )

    for script_name, description in processor_scripts.items():
        script_doc = generate_markdown(description)
        script_filename = f"{os.path.splitext(script_name)[0]}.md"
        script_path = os.path.join(wiki_repo_directory, "processors", script_filename)
        with open(script_path, "w") as f:
            f.write(script_doc)

    for script_name, description in munki_scripts.items():
        script_doc = generate_markdown(description)
        script_filename = f"{os.path.splitext(script_name)[0]}.md"
        script_path = os.path.join(wiki_repo_directory, "munki", script_filename)
        with open(script_path, "w") as f:
            f.write(script_doc)

    for script_name, description in regular_scripts.items():
        script_doc = generate_markdown(description)
        script_filename = f"{os.path.splitext(script_name)[0]}.md"
        script_path = os.path.join(wiki_repo_directory, "scripts", script_filename)
        with open(script_path, "w") as f:
            f.write(script_doc)

    for script_name, description in test_scripts.items():
        script_doc = generate_markdown(description)
        script_filename = f"{os.path.splitext(script_name)[0]}.md"
        script_path = os.path.join(wiki_repo_directory, "testers", script_filename)
        with open(script_path, "w") as f:
            f.write(script_doc)

    os.chdir(wiki_repo_directory)
    subprocess.run(["git", "add", "."])
    subprocess.run(
        ["git", "commit", "-m", "Update script documentation and _Sidebar.md"]
    )
    subprocess.run(["git", "push"])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 generate_wiki.py /path/to/repo")
        sys.exit(1)
    repo_directory = sys.argv[1]
    main(repo_directory)
