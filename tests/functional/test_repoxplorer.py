#!/bin/env python
#
# Copyright (C) 2016 Red Hat
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os
import shutil
import config
import requests

from utils import Base
from utils import set_private_key
from utils import skipIfServiceMissing
from utils import GerritGitUtils
from utils import create_random_str
from utils import JenkinsUtils

from pysflib.sfgerrit import GerritUtils


class TestRepoxplorer(Base):

    def setUp(self):
        super(TestRepoxplorer, self).setUp()
        priv_key_path = set_private_key(
            config.USERS[config.ADMIN_USER]["privkey"])
        self.gitu_admin = GerritGitUtils(
            config.ADMIN_USER,
            priv_key_path,
            config.USERS[config.ADMIN_USER]['email'])
        self.gu = GerritUtils(
            config.GATEWAY_URL,
            auth_cookie=config.USERS[config.ADMIN_USER]['auth_cookie'])
        self.ju = JenkinsUtils()

        self.dirs_to_delete = []

    def tearDown(self):
        super(TestRepoxplorer, self).tearDown()
        for dirs in self.dirs_to_delete:
            shutil.rmtree(dirs)

    def clone_as_admin(self, pname):
        url = "ssh://%s@%s:29418/%s" % (config.ADMIN_USER,
                                        config.GATEWAY_HOST,
                                        pname)
        clone_dir = self.gitu_admin.clone(url, pname)
        if os.path.dirname(clone_dir) not in self.dirs_to_delete:
            self.dirs_to_delete.append(os.path.dirname(clone_dir))
        return clone_dir

    def commit_direct_push_as_admin(self, clone_dir, msg):
        # Stage, commit and direct push the additions on master
        self.gitu_admin.add_commit_for_all_new_additions(clone_dir, msg)
        return self.gitu_admin.direct_push_branch(clone_dir, 'master')

    def set_resources_then_direct_push(self, fpath,
                                       resources=None, mode='add'):
        config_clone_dir = self.clone_as_admin("config")
        path = os.path.join(config_clone_dir, fpath)
        if mode == 'add':
            file(path, 'w').write(resources)
        elif mode == 'del':
            os.unlink(path)
        change_sha = self.commit_direct_push_as_admin(
            config_clone_dir,
            "Add new resources for functional tests")
        config_update_log = self.ju.wait_for_config_update(change_sha)
        self.assertIn("Finished: SUCCESS", config_update_log)

    def get_projects(self):
        url = config.GATEWAY_URL + "/repoxplorer/projects.json/"
        resp = requests.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def get_groups(self):
        url = config.GATEWAY_URL + "/repoxplorer/api_groups.json/"
        resp = requests.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    @skipIfServiceMissing('repoxplorer')
    def test_repoxplorer_accessible(self):
        """ Test if RepoXplorer is accessible on gateway hosts
        """
        url = config.GATEWAY_URL + "/repoxplorer/"
        resp = requests.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue('[RepoXplorer] - Projects listing' in resp.text)

    @skipIfServiceMissing('repoxplorer')
    def test_repoxplorer_data_indexed(self):
        """ Test if RepoXplorer has indexed the config repository
        """
        url = config.GATEWAY_URL + "/repoxplorer/commits.json?pid=internal"
        resp = requests.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()[2] > 0)

    @skipIfServiceMissing('repoxplorer')
    def test_repoxplorer_displayed_top_menu(self):
        """ Test if RepoXplorer link is displayed in the top menu
        """
        url = config.GATEWAY_URL + "/topmenu.html"
        resp = requests.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue('href="/repoxplorer/"' in resp.text,
                        'repoxplorer not present as a link')

    @skipIfServiceMissing('repoxplorer')
    def test_repoxplorer_config_from_resources(self):
        """ Test if RepoXPlorer is reconfigured from new resources
        """
        fpath = "resources/%s.yaml" % create_random_str()
        resources = """resources:
  projects:
    %(pname)s:
      description: An awesome project
      source-repositories:
        - %(pname)s/%(rname)s
  repos:
    %(pname)s/%(rname)s:
      description: The server part
      acl: %(pname)s
  acls:
    %(pname)s:
      file: |
        [access "refs/*"]
          read = group Anonymous Users
  groups:
    %(gname)s:
      description: test for functional test
      members:
        - user2@sftests.com
"""
        tmpl_keys = {'pname': create_random_str(),
                     'rname': create_random_str(),
                     'gname': create_random_str()}

        resources = resources % tmpl_keys
        self.set_resources_then_direct_push(fpath,
                                            resources=resources,
                                            mode='add')
        projects = self.get_projects()
        groups = self.get_groups()

        self.assertIn(tmpl_keys['gname'], groups.keys())
        self.assertIn(tmpl_keys['pname'], projects['projects'].keys())
        project_repos = [r['name'] for r in
                         projects['projects'][tmpl_keys['pname']]]
        self.assertIn(tmpl_keys['pname'] + '/' + tmpl_keys['rname'],
                      project_repos)

        self.set_resources_then_direct_push(fpath,
                                            mode='del')

        projects = self.get_projects()
        groups = self.get_groups()

        self.assertNotIn(tmpl_keys['gname'], groups.keys())
        self.assertNotIn(tmpl_keys['pname'], projects['projects'].keys())
