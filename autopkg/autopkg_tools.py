#!/usr/bin/python3

# Copyright (c) Facebook, Inc. and its affiliates.
# Modifications copyright (C) 2021 Ada Health GmbH
# Modification copyright (c) 2022 Catawiki
# Further modification copyright (c) 2024 Tom Tunberg
"""Wrapper script for handling AutoPKG operations."""

import os
import json
import subprocess
import plistlib
import traceback
from datetime import date
from datetime import datetime
from datetime import timezone
import requests

WEBHOOK_URL = os.environ["SLACK_WEBHOOK"]
GIT = "/usr/bin/git"
GITHUB_CLI = "gh"
REPO_DIR = os.environ["GITHUB_WORKSPACE"] + "/munki_repo"
PKGSINFO_DIR = os.environ["GITHUB_WORKSPACE"] + "/munki_repo" + "/pkgsinfo"
CATALOGS_DIR = os.environ["GITHUB_WORKSPACE"] + "/munki_repo" + "/catalogs"
RECIPE_DIR = os.environ["GITHUB_WORKSPACE"] + "/autopkg/RecipeOverrides"
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
INPUT_RECIPES = os.environ["INPUT_RECIPES"].split()
REVIEWERS = os.environ["REVIEWERS"].split(",")


class Error(Exception):
    """Base class for domain-specific exceptions."""


class GitError(Error):
    """Git exceptions."""


class BranchError(Error):
    """Branch-related exceptions."""


# Utility functions
def run_cmd(cmd):
    """Run a command and return the output."""
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        results_dict = {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "status": proc.returncode,
            "success": proc.returncode == 0,
        }
        return results_dict
    except subprocess.SubprocessError as e:
        print(f"Subprocess failed: {e}")
        return {
            "stdout": b"",
            "stderr": f"SubprocessError: {e}".encode("utf-8"),
            "status": -1,
            "success": False,
        }


def run_live(command):
    """Run a command with real-time output"""
    proc = subprocess.run(command, stderr=subprocess.PIPE, text=True)
    results_dict = {
        "status": proc.returncode,
        "success": proc.returncode == 0,
        "stderr": proc.stderr,
    }
    return results_dict


# Recipe handling
def get_recipes():
    """Create the list of overrides to run"""
    recipes = []
    for root, dirs, files in os.walk("autopkg/RecipeOverrides"):
        for file in files:
            if file.endswith(".recipe") or file.endswith(".recipe.yaml"):
                recipes.append(file)
    return recipes


def parse_recipe_name(identifier):
    """Get the name of the recipe."""
    recipename = identifier.replace(" ", "-").lower().split(".munki")[0]
    return recipename


def parse_report_plist(report_plist_path):
    """Parse the report plist path for a dict of the results."""
    imported_items = []
    failed_items = []
    virus_total_items = []
    with open(report_plist_path, "rb") as file:
        report_data = plistlib.load(file)
    if report_data["summary_results"]:
        # This means something happened
        munki_results = report_data["summary_results"].get(
            "munki_importer_summary_result", {}
        )
        # Get the latest data_rows item name from the munki_importer_summary_result
        for imported_item in munki_results.get("data_rows", []):
            imported_items.append(imported_item)
        # Get the latest data_rows for the virus total scan result
        virustotal_results = report_data["summary_results"].get(
            "virus_total_analyzer_summary_result", {}
        )
        for virustotal_item in virustotal_results.get("data_rows", []):
            virus_total_items.append(virustotal_item)
    if report_data["failures"]:
        # This means something went wrong
        for failed_item in report_data["failures"]:
            # For each recipe that failed, file a task
            failed_items.append(failed_item)
    return {
        "imported": imported_items,
        "failed": failed_items,
        "virus_total": virus_total_items,
    }


# Git/Hub-related functions
def issue_exists(issue_title):
    """
    Check if an issue with the given title already exists
    and return its URL and number if it does.
    """
    command = [
        "gh",
        "issue",
        "list",
        "--search",
        issue_title,
        "--state",
        "all",
        "--json",
        "title,url,number,state,updatedAt",
    ]
    result = run_cmd(command)
    if result["success"]:
        issues = json.loads(result["stdout"])
        for issue in issues:
            if issue_title.lower() == issue["title"].lower():
                return (
                    True,
                    issue["url"],
                    str(issue["number"]),
                    issue["state"],
                    issue["updatedAt"],
                )
    return False, None, None, None, None


def get_issue_comments(issue_number):
    """
    Retrieve comments for a given issue number.
    """
    command = ["gh", "issue", "view", issue_number, "--json", "comments"]
    result = run_cmd(command)
    if result["success"]:
        issue_data = json.loads(result["stdout"])
        comments = issue_data.get("comments", [])
        return comments
    return []


def add_comment_to_issue(issue_url, comment_body):
    """Add a comment to an existing GitHub issue."""
    issue_number = issue_url.rstrip("/").split("/")[-1]
    command = ["gh", "issue", "comment", issue_number, "--body", comment_body]
    result = run_cmd(command)
    if result["success"]:
        print(f"Comment added to issue: {issue_url}")
    else:
        print(f"Failed to add comment: {result['stderr']}")


def close_github_issue(issue_number, issue_url, comment_body):
    command = ["gh", "issue", "close", issue_number, "--comment", comment_body]
    result = run_cmd(command)
    if result["success"]:
        print(f"Issue closed: {issue_url}")
    else:
        print(f"Failed to close issue: {result['stderr']}")


def reopen_github_issue(issue_number, comment_body):
    command = ["gh", "issue", "reopen", issue_number, "--comment", comment_body]
    result = run_cmd(command)
    if result["success"]:
        print(f"Issue reopened: #{issue_number}")
        reopened_comment_time = datetime.now(timezone.utc).isoformat()
        return reopened_comment_time
    else:
        print(f"Failed to reopen issue: {result['stderr']}")
        return None


def create_github_issue(issue_title, issue_body):
    """Create GitHub issue"""
    exists, issue_url, issue_number, issue_state, issue_updated_at = issue_exists(
        issue_title
    )
    if exists:
        if issue_state == "CLOSED":
            updated_date = datetime.strptime(
                issue_updated_at, "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - updated_date).days <= 6:
                reopen_comment = f"Reopening issue due to new error: {issue_body}"
                reopened_comment_time = reopen_github_issue(
                    issue_number, reopen_comment
                )
                return issue_url, reopened_comment_time
        else:
            print(f"Issue exists already as #{issue_number}")
            comment_body = f"Latest AutoPkg run error message: {issue_body}"
            add_comment_to_issue(issue_url, comment_body)
            return issue_url, None
    command = ["gh", "issue", "create", "--title", issue_title, "--body", issue_body]
    result = run_cmd(command)
    issue_url = result.get("stdout", "").strip()
    return issue_url, None


def handle_existing_issue_on_success(recipe_name):
    """
    Handle cases where there's an open issue and we
    have an AutoPkg success run for the given recipe.
    """
    exists, issue_url, issue_number, issue_state, _ = issue_exists(recipe_name)
    if exists:
        comments = get_issue_comments(issue_number)
        only_github_actions = all(
            comment["author"]["login"] == "github-actions" for comment in comments
        )
        comment_body = f"{recipe_name} has run successfully. This issue should be closed automatically. Testing..."
        add_comment_to_issue(issue_url, comment_body)
        if only_github_actions:
            comment_body = f"This issue, #{issue_number}, has only comments from github-actions, and it is in {issue_state}. Not closing this before a human comments what changed."
            add_comment_to_issue(issue_url, comment_body)
        else:
            comment_body = "Closing this as resolved."
            close_github_issue(issue_number, issue_url, comment_body)


def create_issue(recipe, error_message):
    """
    Handle creating a GitHub issue on run failures.
    """
    issue_title = f"{recipe}"
    issue_body = f"{error_message}"
    issue_URL, _ = create_github_issue(issue_title, issue_body)
    return issue_URL


def git_run(arglist):
    """Run git with the argument list."""
    # Only run git commands in the munki repo dir
    owd = os.getcwd()
    os.chdir(REPO_DIR)
    gitcmd = [GIT] + [str(arg) for arg in arglist]
    results = run_cmd(gitcmd)
    os.chdir(owd)
    if not results["success"]:
        raise GitError("Git error: %s" % results["stderr"])
    return results["stdout"]


def branch_list():
    """Get the list of current git branches."""
    git_args = ["branch"]
    branch_output = git_run(git_args).rstrip()
    if branch_output:
        return [x.strip().strip("* ") for x in branch_output.decode().split("\n")]
    return []


def current_branch():
    """Return the name of the current git branch."""
    git_args = ["symbolic-ref", "--short", "HEAD"]
    return str(git_run(git_args).strip())


def create_feature_branch(branchname):
    """Create new feature branch."""
    if current_branch() != "master":
        # switch to master first if we're not already there
        change_feature_branch("master")
    # check if the branch already exists, add -2 if so
    existing_branch = branch_exists(branchname)
    if existing_branch:
        branchname = f"{branchname}-2"
    change_feature_branch(branchname, new=True)


def branch_exists(branchname):
    """Check if the branch exists."""
    git_args = ["git", "ls-remote", "--exit-code", "origin", branchname]
    try:
        result = run_cmd(git_args)
        # check based on return code
        if result["status"] == 0:
            return True  # exists
        elif result["status"] == 2:
            return False  # does not exist
        else:
            print(f"Error checking branch: {result['stderr']}")
            return True  # we proceed to change branchname on error
    except GitError:
        return False


def change_feature_branch(branchname, new=False):
    """Swap to feature branch."""
    gitcmd = ["checkout"]
    if new:
        gitcmd.append("-b")
    gitcmd.append(branchname)
    try:
        git_run(gitcmd)
    except GitError as e:
        raise BranchError("Couldn't switch to '%s': %s" % (branchname, e))


def create_commit(imported_item):
    """Create git commit."""
    print("Adding items...")
    gitaddcmd = ["add", PKGSINFO_DIR, CATALOGS_DIR]
    git_run(gitaddcmd)
    print("Creating commit...")
    gitcommitcmd = ["commit", "-m"]
    message = "update %s to version %s" % (
        str(imported_item["name"]),
        str(imported_item["version"]),
    )
    gitcommitcmd.append(message)
    git_run(gitcommitcmd)


def git_push(branchname):
    """Perform a git push."""
    print("Running `git push`...")
    gitpushcmd = ["push", "--set-upstream", "origin"]
    gitpushcmd.append(branchname)
    try:
        git_run(gitpushcmd)
    except GitError as e:
        print("Failed to push branch %s" % branchname)
        traceback.print_exc()  # Print the traceback
        return {
            "success": False,
            "error": str(e),  # exception to string
            "branch": branchname,
        }
    return {"success": True}


def pull_request(branchname):
    """Create Pull request using the gh cli tool."""
    if not GITHUB_TOKEN:
        print("Pull request not created.. GITHUB_TOKEN not set")
        return
    print("Creating Pull Request...")
    run_cmd([GITHUB_CLI, "pr", "create", "-B", "master", "-H", branchname, "-f"])


def pull_request_link(branchname):
    """Get Pull Request Link"""
    prcmd = [GITHUB_CLI, "pr", "view", "--json", "url", "-q", ".url"]
    try:
        link = run_cmd(prcmd)
        print("Got PR link")
        return link
    except GitError as e:
        print("Failed to get pull request link from %s" % branchname)


# Slack related functions
def imported_message(imported, virus_total_results):
    """Format a list of imported items for a Slack message"""
    imported_msg = [
        {
            "type": "section",
            "text": {
                "type": "plain_text",
                "text": "The following items will be imported into munki after approval",
            },
        }
    ]

    for i in range(len(imported)):
        item = imported[i]
        version = item["version"]
        name = item["recipename"]
        permalink = virus_total_results[i]

        if not permalink or permalink == "None":
            imported_info = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"• {name} version {version}"},
                }
            ]
        else:
            imported_info = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"• <{permalink}|{name}> version {version}",
                    },
                }
            ]

        imported_msg.extend(imported_info)

    return imported_msg


def failures_message(failed):
    """Format a list of failed recipes for a slack message"""
    failures_msg = [
        {
            "color": "#f2c744",
            "blocks": [
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":warning: *The following recipes failed*",
                    },
                },
            ],
        }
    ]
    for item in failed:
        info = item["message"]
        name = item["recipe"]
        failure_info = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"{name}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"```{info}```"}},
        ]
        failures_msg[0]["blocks"].extend(failure_info)
    return failures_msg


def git_pr_message(pr_link, build_duration, issues):
    """Format the PR URL and build duration to send as slack message"""
    git_msg = [
        {
            "color": "#054efa",
            "blocks": [
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f":hourglass_flowing_sand: Build duration: {build_duration}",
                        }
                    ],
                },
            ],
        }
    ]
    if not pr_link or pr_link == "None":
        link_msg = [
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": ":warning: No link available."}
                ],
            }
        ]
        git_msg[0]["blocks"].extend(link_msg)
    else:
        link_msg = [
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f":git-merged: Link to PR: {pr_link}"}
                ],
            }
        ]
        git_msg[0]["blocks"].extend(link_msg)
    if issues:
        issue_count = len(issues)
        issue_msg = [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f":internet-problems: Issues created: {issue_count}",
                    }
                ],
            }
        ]
        git_msg[0]["blocks"].extend(issue_msg)
    return git_msg


def format_slack_message(
    imported, failed, link_msg, virus_total_results, build_duration, issues
):
    """Compose notification to be sent to slack"""
    message = {
        "blocks": [],
        "attachments": [
            {
                "color": "#4bb543",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": ":package: *AutoPkg has finished running*",
                        },
                    }
                ],
            }
        ],
    }
    if not imported:
        msg_info = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "There are no new items to be imported into Munki",
                },
            }
        ]
        message["attachments"][0]["blocks"].extend(msg_info)
    else:
        message["attachments"][0]["blocks"].extend(
            imported_message(imported, virus_total_results)
        )
    if failed:
        message["attachments"].extend(failures_message(failed))
    if link_msg:
        message["attachments"].extend(git_pr_message(link_msg, build_duration, issues))

    return message


def post_to_slack(message):
    """Post slack message to the WEBHOOK_URL"""
    if not WEBHOOK_URL:
        print("Slack Webhook not set.. No notification sent.")
        return
    response = requests.post(
        WEBHOOK_URL,
        data=json.dumps(message),
        headers={"Content-Type": "application/json"},
    )
    print(f"Slack Message post status: {response.status_code}: {response.text}")


# Autopkg execution functions
def autopkg_verify_update(recipe):
    """Run verification and update on a recipe trust if it fails"""
    verify_cmd = ["/usr/local/bin/autopkg", "verify-trust-info", recipe]
    verification_result = run_live(verify_cmd)

    if not verification_result["success"]:
        update_cmd = ["/usr/local/bin/autopkg", "update-trust-info", recipe]
        run_live(update_cmd)
        recipeaddcmd = ["add"]
        recipeaddcmd.append(RECIPE_DIR)
        git_run(recipeaddcmd)


def autopkg_run(recipe):
    """Run autopkg on given recipe"""
    autopkg_verify_update(recipe)
    autopkg_cmd = ["/usr/local/bin/autopkg", "run", "-vvv"]
    autopkg_cmd.append(recipe)
    autopkg_cmd.append("--report-plist")
    autopkg_cmd.append("report.plist")
    autopkg_cmd.append("--post")
    autopkg_cmd.append("io.github.hjuutilainen.VirusTotalAnalyzer/VirusTotalAnalyzer")
    run_live(autopkg_cmd)


def handle_recipes():
    imported = []
    failed = []
    issues = []
    virus_total_results = []
    today = date.today()
    branchname = f"munkiapps_{today}"
    if INPUT_RECIPES:
        recipes = INPUT_RECIPES
    else:
        recipes = get_recipes()
    # Start the timer
    start_time = datetime.now()
    # Create the new branch
    create_feature_branch(branchname)
    # Run the recipe (file) list
    for recipe in recipes:
        # Parse the recipe name for basic item name
        recipename = parse_recipe_name(recipe)
        # change to branch that was created above
        change_feature_branch(branchname)
        # Run Autopkg
        autopkg_run(recipe)
        # Parse the results from report plist
        run_results = parse_report_plist("report.plist")
        if not run_results["imported"] and not run_results["failed"]:
            # Nothing happened
            continue
        if run_results["failed"]:
            # Add to list of failed items
            failed.append(run_results["failed"][0])
            # create issue
            for item in run_results["failed"]:
                recipe_name = item["recipe"]
                error_message = item["message"]
                issue_URL = create_issue(recipe_name, error_message)
                issues.append(issue_URL)
        if run_results["imported"]:
            # Commit changes
            create_commit(run_results["imported"][0])
            # Push to github
            push_result = git_push(branchname)
            if not push_result["success"]:
                continue
            else:
                # Add basic item name to imported results so we can tell the difference between arm and intel items
                run_results["imported"][0]["recipename"] = recipename
                # Add to list of imported items
                imported.append(run_results["imported"][0])
                # Add the VirusTotal link
                virus_total_items = run_results["virus_total"]
                if virus_total_items:
                    virus_total_item = virus_total_items[0]
                    permalink = virus_total_item.get("permalink")
                    virus_total_results.append(permalink)
                else:
                    virus_total_results.append(None)
                handle_existing_issue_on_success(recipe)

    remove_munkitools_folder()
    # Create the PR
    pull_request(branchname)
    # obtain the url from json output of gh
    git_pr = pull_request_link(branchname)
    # extract the pr from the function
    pr_formatting = git_pr.get("stdout")
    # output has extra characters, we remove those
    pr_link = pr_formatting.decode("utf-8").replace("\n", "")
    # we want the last item in the text
    extract_pr = pr_link.split("/")
    pr_number = extract_pr[-1]
    # get duration of the AutoPkg run, convert to proper time format
    end_time = datetime.now()
    elapsed_time = end_time - start_time
    # total seconds is a method from timedelta
    elapsed_seconds = elapsed_time.total_seconds()
    # divmod returns a tuple of the quotient and the remainder
    hours, remainder = divmod(elapsed_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    build_duration = f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
    # Send a report of what happened to slack
    slack_notification = format_slack_message(
        imported, failed, pr_link, virus_total_results, build_duration, issues
    )
    post_to_slack(slack_notification)


if __name__ == "__main__":
    handle_recipes()
