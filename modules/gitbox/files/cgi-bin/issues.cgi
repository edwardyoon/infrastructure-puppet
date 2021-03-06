#!/usr/bin/env python
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# This is issues.cgi: Handler for GitHub issues (and PRs)

import hashlib, json, random, os, sys, time, subprocess
import cgi, netaddr, smtplib, sqlite3, git
from email.mime.text import MIMEText

# Define some defaults and debug vars
DEBUG_MAIL_TO = "humbedooh@apache.org" # Set to a var to override mail recipients, or None to disable.
DEFAULT_SENDMAIL = True             # Should we default to sending an email to the list? (this is very rarely no)
DEFAULT_JIRA_ENABLED = True         # Is JIRA bridge enabled by default?
DEFAULT_JIRA_ACTION = "comment"     # Default JIRA action (comment/worklog)

# CGI interface
xform = cgi.FieldStorage();

# Check that this is GitHub calling
from netaddr import IPNetwork, IPAddress
GitHubNetwork = IPNetwork("192.30.252.0/22") # This is GitHub's current
                                             # net block. May change!
callerIP = IPAddress(os.environ['REMOTE_ADDR'])
if not callerIP in GitHubNetwork:
    print("Status: 401 Unauthorized\r\nContent-Type: text/plain\r\n\r\nI don't know you!\r\n")
    sys.exit(0)


### Helper functions ###
def getvalue(key):
    val = xform.getvalue(key)
    if val:
        return val
    else:
        return None

def sendEmail(rcpt, subject, message):
    sender = "<git@git.apache.org>"
    receivers = [rcpt]
    msg = """From: %s
To: %s
Subject: %s

%s

With regards,
Apache Git Services
""" % (sender, rcpt, subject, message)

    try:
        smtpObj = smtplib.SMTP("localhost")
        smtpObj.sendmail(sender, receivers, msg)
    except SMTPException:
        raise Exception("Could not send email - SMTP server down??")


################################
# Message formatting functions #
################################

TMPL_NEW_TICKET = """
GitHub user %(user)s opened a new %(type)s: %(title)s

%(text)s

You can view it online at: %(link)s
"""

TMPL_CLOSED_TICKET = """
GitHub user %(user)s closed #%(id)i: %(title)s

You can view it online at: %(link)s
"""

TMPL_GENERIC_COMMENT = """
GitHub user %(user)s commented on %(type)s #%(id)i: %(title)s:

%(text)s

You can view it online at: %(link)s
"""

def issueOpened(payload):
    fmt = {}
    fmt['user'] = payload['user']['login']
    obj = payload['pull_request'] if 'pull_request' in payload else payload['issue']
    # PR or issue??
    fmt['type'] = 'issue'
    if 'pull_request' in payload:
        fmt['type'] = 'pull request'
    fmt['id'] = obj['number']
    fmt['text'] = obj['body']
    fmt['title'] = obj['title']
    fmt['link'] = obj['html_url']
    email = {
        'subject': "New GitHub %(type)s: %(title)s" % fmt,
        'message': TMPL_NEW_TICKET % fmt
    }
    return email

def issueClosed(payload):
    fmt = {}
    fmt['user'] = payload['user']['login']
    obj = payload['pull_request'] if 'pull_request' in payload else payload['issue']
    # PR or issue??
    fmt['type'] = 'issue'
    if 'pull_request' in payload:
        fmt['type'] = 'pull request'
    fmt['id'] = obj['number']
    fmt['text'] = obj['body']
    fmt['title'] = obj['title']
    fmt['link'] = obj['html_url']
    email = {
        'subject': "GitHub %(type)s #(%id)i closed: %(title)s" % fmt,
        'message': TMPL_NEW_TICKET % fmt
    }
    return email


def ticketComment(payload):
    fmt = {}
    obj = payload['pull_request'] if 'pull_request' in payload else payload['issue']
    comment = obj['comment']
    # PR or issue??
    fmt['type'] = 'issue'
    if 'pull_request' in payload:
        fmt['type'] = 'pull request'
    # This is different from open/close payloads!
    fmt['user'] = comment['user']['login']
    fmt['id'] = obj['number']
    fmt['text'] = comment['body']
    fmt['title'] = obj['title']
    fmt['link'] = comment['html_url']
    email = {
        'subject': "%(user) commented on #%(id)i: %(title)s" % fmt,
        'message': TMPL_GENERIC_COMMENT % fmt
    }
    return email


# Main function
def main():
    # Get JSON payload from GitHub
    jsin = getvalue('payload')
    data = json.loads(jsin)
    
    # Now check if this repo is hosted on GitBox (if not, abort):
    if'repository' in data:
        repo = data['repository']
        repopath = "/x1/repos/asf/%s.git" % repo
    else:
        return None
    if not os.path.exists(repopath):
        return None
    
    # Get configuration options for the repo
    configpath = os.path.join(repopath, "config")
    if os.path.exists(configpath):
        gconf = git.GitConfigParser(configpath, read_only = True)
    else:
        return "No configuration found for repository %s" % repo
    
    # Get recipient email address for mail coms
    m = re.match(r"(?incubator-)([^-]+)", repo)
    project = "infra" # Default to infra
    if m:
        project = m.group(1)
    mailto = gconf.get('apache', 'dev') if gconf.has_section('apache') and gconf.has_option('apache', 'dev') else "dev@%s.apache.org" % project
    # Debug override if testing
    if DEBUG_MAIL_TO:
        mailto = DEBUG_MAIL_TO
    
    # Now figure out what type of event we got
    email = None
    if 'action' in data:
        # Issue opened or reopened
        if data['action'] in ['opened', 'reopened']:
            email = issueOpened(data)
        # Issue closed
        elif data['action'] == 'closed':
            email = issueClosed(data)
        # Comment on issue or specific code (WIP)
        elif 'comment' in data:
            # File-specific comment
            if 'path' in data['comment']:
                pass
            # Standard commit comment
            elif 'commit_id' in data['comment']:
                pass
            # Generic comment
            else:
                email = ticketComment(data)
    
    # Send email if applicable
    if email:
        sendEmail(mailto, email['subject'], email['message'])
        
    # All done!
    return None

if __name__ == '__main__':
    rv = main()                                          # run main block
    print("Status: 204 Message received\r\n\r\n")   # Always return this
    # If error was returned, log it in issues.log
    if rv:
        open("/x1/gitbox/issues.log", "a").write(rv + "\r\n")
    
