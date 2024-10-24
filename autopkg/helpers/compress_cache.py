"""
Used for gathering up the json files that the URLDownloaderPython creates
for each download.
This helps speed up the AutoPkg runs, as we look for the json cache before
proceeding with any application download, which is the normal behaviour.
"""

import os
import tarfile
import shutil


def create_tar_gz(autopkg_directory, tar_archive_name, destination_directory):
    autopkg_dir = os.path.join(autopkg_directory, "Cache")
    os.chdir(autopkg_dir)
    with tarfile.open(tar_archive_name, "w:gz") as tar_file:
        for foldername, subfolders, filenames in os.walk("."):
            for filename in filenames:
                if filename.endswith(".info.json"):
                    file_path = os.path.join(foldername, filename)
                    arcname = os.path.relpath(file_path, autopkg_directory)
                    tar_file.add(file_path, arcname=arcname)

    shutil.move(tar_archive_name, os.path.join(destination_directory, tar_archive_name))


autopkg_directory = os.environ.get("autopkg_dir")
tar_archive_name = os.environ.get("archive_name")
destination_directory = os.environ.get("GITHUB_WORKSPACE")

create_tar_gz(autopkg_directory, tar_archive_name, destination_directory)
