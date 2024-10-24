import os
from datetime import datetime, timezone, timedelta
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

"""
This python script handles the Slack result output of the Munki manifest creation or edits.

How it works:
It sends one message with one Serial number to begin with.
If there are more manifests being added (read: users onboarding one after another, which fires off the trigger),
this first message gets each serial number added to it, instead of multiple Slack messages spamming a channel.
It has a limit of an hour before sending a new message with a new serial number of the client enrolling.
"""


def create_or_update_manifests():
    client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
    try:
        user_name = os.environ["LOGIN"]
        if os.environ["PR_NUMBER"]:
            pr_number = f"<https://github.com/{os.environ['REPO_NAME']}/pull/{os.environ['PR_NUMBER']}|{os.environ['PR_NUMBER']}>"
        else:
            pr_number = "No change needed"
        # set times
        current_datetime_utc = datetime.now(timezone.utc)
        three_hours_ago_utc = current_datetime_utc - timedelta(hours=3)
        # check messages from 8am
        response = client.conversations_history(
            channel=os.environ["CHANNEL_ID"],
            oldest=three_hours_ago_utc.timestamp(),
            latest=current_datetime_utc.timestamp(),
        )
        messages = response["messages"]
        print(f"messages: {messages}")
        message_found = False
        for message in messages:
            # find if a message from the bot exists in the messages variable
            if "bot_id" in message and message["bot_id"] == os.environ["BOT_ID"]:
                print(f"bot id: {message['bot_id']}")
                blocks = message.get("blocks", [])
                # if the history includes a message with our search criteria
                for block in blocks:
                    if (
                        block["type"] == "section"
                        and "text" in block["text"]
                        and ":monkey: *New Munki Manifest(s)!*" in block["text"]["text"]
                    ):
                        # we add an identical line to the first serial message
                        new_serial_line = f":file_folder: Serial: {os.environ['NEW_SERIAL']} :git: PR: {pr_number} :computer: {user_name}\n"
                        # keeping the block above in mind, we insert the json below right after it
                        # with the above new_serial_line included
                        blocks.insert(
                            blocks.index(block) + 1,
                            {
                                "type": "context",
                                "elements": [
                                    {"type": "mrkdwn", "text": new_serial_line}
                                ],
                            },
                        )
                        # Update the message with modified blocks
                        client.chat_update(
                            channel=os.environ["CHANNEL_ID"],
                            ts=message["ts"],
                            blocks=blocks,
                        )
                        return f"Serial section added: {os.environ['NEW_SERIAL']}"
                    elif not message_found:
                        message_found = True

        if not message_found:
            # No message with the matching section found, create a new message
            new_blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":monkey: *New Munki Manifest(s)!*",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f":file_folder: Serial: {os.environ['NEW_SERIAL']} :git: PR: {pr_number} :computer: {user_name}\n",
                        }
                    ],
                },
            ]
            response = client.chat_postMessage(
                channel=os.environ["CHANNEL_ID"], blocks=new_blocks
            )
            return f"Serial section created: {os.environ['NEW_SERIAL']}, Message created: {response['ts']}"

        return "No matching message found."

    except SlackApiError as e:
        return f"Error: {e}"


result = create_or_update_manifests()
print(result)
