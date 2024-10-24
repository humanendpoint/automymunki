"""
Generates or edits Munki manifests, this script requires some input vars to work.
You can add these to a github action env, otherwise your local env also works.

Does not take into account any really complex manifest creations, but does accept
optional_installs and additional_catalogs; which are typically used customizations.
"""

import os
import plistlib
import requests

OKTA_API_URL = os.environ.get("OKTA_DOMAIN")
OKTA_API_TOKEN = os.environ.get("OKTA_API_TOKEN")


def get_input_values():
    # Retrieve values from environment variables
    display_name = os.environ.get("LOGIN")
    group = os.environ.get("DEPARTMENT")
    optional_installs = os.environ.get("OPTIONAL_INSTALLS", "")
    additional_catalogs = os.environ.get("ADDITIONAL_CATALOGS", "")
    serial = os.environ.get("SERIAL")

    optional_installs = optional_installs.split(",") if optional_installs else []
    additional_catalogs = additional_catalogs.split(",") if additional_catalogs else []

    return display_name, group, optional_installs, additional_catalogs, serial


def get_user_profile(display_name):
    try:
        headers = {"Authorization": f"SSWS {OKTA_API_TOKEN}"}

        # Make a request to Okta to get user profile based on display name
        response = requests.get(
            f"https://{os.environ.get('OKTA_DOMAIN')}.okta.com/api/v1/users/{display_name}%40{os.environ.get('OKTA_DOMAIN')}.com",
            headers=headers,
        )

        response.raise_for_status()
        user_info = response.json()
        if user_info:
            user_id = user_info[0]["id"]
            manager = user_info[0]["isManager"]

            # inspect user profile
            # e.g. check user group or other profile attributes
            # replace the following line with desired inspection and logic
            user_profile = {}

            return user_profile
        else:
            return {}
    except requests.exceptions.RequestException as e:
        print(f"Error while fetching user profile from Okta: {e}")
        return {}


# def customize_manifest(manifest_dict, user_profile):
#    # Customize the manifest based on user profile
# For example, add or remove items from the manifest based on user attributes
#    if user_profile.get(""):
#        manifest_dict["optional_installs"].append("thisOtherCoolApp")


def update_or_create_manifest(
    manifest_path, display_name, group, optional_installs, additional_catalogs
):
    try:
        if os.path.exists(manifest_path):
            # exists, load it
            with open(manifest_path, "rb") as file:
                existing_manifest = plistlib.load(file)
            # modify existing manifest with new data
            existing_manifest = create_manifest(
                display_name, group, optional_installs, additional_catalogs
            )
        else:
            # doesn't exist
            existing_manifest = create_manifest(
                display_name, group, optional_installs, additional_catalogs
            )

        # if "user_profile_check" in group:
        #    # Further actions based on user profile
        #    user_profile = get_user_profile(display_name)
        #    # Customize manifest based on user profile
        #    customize_manifest(existing_manifest, user_profile)

        # save
        with open(manifest_path, "wb") as file:
            plistlib.dump(existing_manifest, file)

        if os.path.exists(manifest_path):
            print(f"Manifest edited: {manifest_path}")
        else:
            print(f"Error: Unable to edit the manifest.")
    except IOError as e:
        print(f"Error: Unable to update the manifest file. {str(e)}")
    except Exception as e:
        print(f"Error: {str(e)}")


def create_manifest(display_name, group, optional_installs, additional_catalogs):
    manifest_dict = {
        "catalogs": ["production"],  # initialize with the default catalog
        "display_name": display_name,
    }

    if "testing" in group:
        manifest_dict["catalogs"].insert(0, "testing")

    if optional_installs:
        manifest_dict["optional_installs"] = optional_installs

    if additional_catalogs:
        manifest_dict["catalogs"] += additional_catalogs

    return manifest_dict


def main():
    (
        display_name,
        group,
        optional_installs,
        additional_catalogs,
        serial,
    ) = get_input_values()

    manifest_path = (
        os.path.join(os.environ.get("GITHUB_WORKSPACE"))
        + f"/munki_repo/manifests/{serial}"
    )

    if not group:
        group = "default"
    if not display_name:
        display_name = "nobody"

    update_or_create_manifest(
        manifest_path, display_name, group, optional_installs, additional_catalogs
    )


if __name__ == "__main__":
    main()
