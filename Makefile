SHELL:=/bin/bash

MUNKI_REPO_NAME?=automymunki


init:
	mkdir ../$(MUNKI_REPO_NAME)
	cp -r . ../$(MUNKI_REPO_NAME)
	cd ../$(MUNKI_REPO_NAME) && rm -rf .git
	cd ../$(MUNKI_REPO_NAME) && git init


lfs:
	cd ../$(MUNKI_REPO_NAME) && git lfs install
	cd ../$(MUNKI_REPO_NAME) && git lfs track "*.pkg"
	cd ../$(MUNKI_REPO_NAME) && git lfs track "*.dmg"
