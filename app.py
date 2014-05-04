import json
import urlparse
from pprint import pprint

from flask import Flask, request, Response
import requests

app = Flask(__name__)
app.debug = True
app.config.from_envvar('SETTINGS_FILE')


@app.route('/api/v1/jira-hook/', methods=('POST',))
def jira_hook():
    hook_data = request.get_json()
    process_issue(hook_data)

    return Response(status=204)


def did_become_blocker(hook_data):
    priority_changes = filter(lambda i: i['field'] == 'priority',
                              hook_data['changelog']['items'])
    if not priority_changes:
        return False

    if priority_changes[0]['to'] == "1":
        return True


def issue_should_resolve(hook_data):
    priority_changes = filter(lambda i: i['field'] == 'priority',
                              hook_data['changelog']['items'])
    if priority_changes and priority_changes[0]['from'] == "1":
        return True

    status_changes = filter(lambda i: i['field'] == 'status',
                            hook_data['changelog']['items'])
    if status_changes and status_changes[0]['to'] == u'6':
        return True


def process_issue(hook_data):
    should_trigger = did_become_blocker(hook_data)

    if should_trigger:
        _trigger(hook_data)
        return

    if issue_should_resolve(hook_data):
        _resolve(hook_data)
        return


def pd_request(**kwargs):
    headers = {
        'content-type': 'application/json'
    }
    if 'headers' in kwargs:
        headers.update(kwargs['headers'])
        del kwargs['headers']

    data = {
        'service_key': app.config['PD_SERVICE_KEY'],
    }
    data.update(kwargs['data'])
    del kwargs['data']

    return requests.post(
        'https://events.pagerduty.com/generic/2010-04-15/create_event.json',
        headers=headers,
        data=json.dumps(data),
        **kwargs
    )


def _resolve(hook_data):
    r = pd_request(data={
        'incident_key': hook_data['issue']['key'],
        'event_type': 'resolve',
        'description': 'issue resolved',
    })

    try:
        r.raise_for_status()
    except requests.exceptions.RequestException:
        print r.text


def _trigger(hook_data):
    # Convert the REST API URL for the issue into a URL for accessing the issue
    # via the JIRA web interface
    pr = urlparse.urlparse(hook_data['issue']['self'])
    issue_url = urlparse.urlunparse((
        pr.scheme,
        pr.netloc,
        '/browse/{key}'.format(key=hook_data['issue']['key']),
        '',
        '',
        '',
    ))

    r = pd_request(data={
        'incident_key': hook_data['issue']['key'],
        'event_type': 'trigger',
        'description': 'New Blocker Issue - {key} - {url}'.format(
            key=hook_data['issue']['key'],
            url=issue_url
        ),
        'details': {
            'Summary': hook_data['issue']['fields']['summary'],
            'Creator': hook_data['issue']['fields']['creator']['displayName'],
            'Assignee': hook_data['issue']['fields']['assignee']['displayName'],
        },
    })

    try:
        r.raise_for_status()
    except requests.exceptions.RequestException:
        print r.text
