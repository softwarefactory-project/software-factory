#!/usr/bin/env python

import argparse
import datetime
from six.moves.urllib.parse import urljoin, unquote_plus
import sys

from pysflib.sfauth import get_cookie
from pysflib.sfstoryboard import SFStoryboard
from storyboardclient._apiclient import exceptions


"""Utility script used by SF scrum masters to manage the backlog and the
sprint ceremonies. The full workflow and definition of the boards are
explained here: https://softwarefactory-project.io/etherpad/p/backlog_ng"""

LANES = ['Groomed Stories',
         'Open Tasks',
         'Open Confirmed Bugs',
         'Blocked',
         'Current Sprint',
         'In Progress',
         'Ready for Review',
         'Done']


class StoryboardManager(object):
    def __init__(self, url, api_key, project_group, board=None,
                 groom_worklist=None, bug_worklist=None):
        self.url = url
        self.cookie = get_cookie(url, api_key=api_key)
        self.client = SFStoryboard(urljoin(url, "storyboard_api"),
                                   self.cookie)
        try:
            self.project_group = self.client.project_groups.find(
                name=project_group)
        except exceptions.NotFound:
            raise Exception('projects group not found')
        self.stories = self.client.stories.get_all(
            project_group_id=self.project_group.id)
        self.board_id = None
        if board:
            try:
                self.board_id = self.client.boards.find(title=board).id
            except exceptions.NotFound:
                raise Exception('board not found')
        self.board_lanes = {}
        for lane in self.client.worklists.get_all(board_id=self.board_id):
            if not lane.archived and lane.title in LANES:
                self.board_lanes[lane.title] = lane
        if groom_worklist:
            try:
                self.groom_worklist = self.client.worklists.find(
                    title=groom_worklist)
            except exceptions.NotFound:
                raise Exception('unrefined stories worklist not found')
        if bug_worklist:
            try:
                self.bug_worklist = self.client.worklists.find(
                    title=bug_worklist)
            except exceptions.NotFound:
                raise Exception('unrefined stories worklist not found')

#    def is_task_part_of_project(self, task):
#        return task.project_id in self.projects_ids

    def find_current_lane(self, item, type):
        lanes = self.board_lanes.values() +\
            [self.groom_worklist, self.bug_worklist, ]
        for lane in lanes:
            for i in lane.items:
                if i['item_type'] == type and i['item_id'] == item.id and\
                 not i['archived']:
                    return lane.id, i['id']
        return None, None

    def move_to_lane(self, item, type, lane_id=None):
        """Move item of type (story or task) to worklist lane_id.
        If lane_id is None, simply remove item from current worklist."""
        current_lane, id_in_lane = self.find_current_lane(item, type)
        if current_lane:
            cl_title = self.client.worklists.get(id=current_lane).title
            print "#%s found in worklist '%s'," % (item.id,
                                                   cl_title),
        if current_lane == lane_id:
            print " nothing to do"
            return
        if current_lane and id_in_lane:
            print " removing"
            r = self.client.delete("worklists/%s/items/" % current_lane,
                               json=dict(item_id=item.id))
                               
            print "del %s" % r.status_code
        if lane_id:
            print "moving #%s to worklist #%s" % (item.id, lane_id)
            r = self.client.post("worklists/%s/items/" % lane_id,
                                 json=dict(item_id=item.id,
                                           item_type=type,
                                           list_position=0))
            print "post %s" % r.status_code

    def get_sprint_boundaries(self):
        due_dates = self.client.due_dates.get_all(board_id=self.board_id)
        return sorted(due_dates, key=lambda x: x.date)[-2:]

    # worklists operations
    def is_to_groom(self, story, regroom_after=None):
        # find stories in project group that are untagged, unassigned,
        # in status "Todo"
        tasks = story.tasks.get_all()
        if all(t.assignee_id == None for t in tasks):
            if all(t.status.lower() == 'todo' for t in tasks):
                if regroom_after == None and 'groomed' not in story.tags:
                    return True
                if regroom_after:
                    delta = datetime.timedelta(days=regroom_after)
                    last_update = datetime.datetime.strptime(
                        story.updated_at,
                        '%Y-%m-%dT%H:%M:%S+00:00')
                    if datetime.datetime.now() - last_update > delta:
                        return True
        return False

    def is_to_triage(self, story):
        # find stories in project group that are tagged "bug" 
        # but not tagged "confirmed"
        if 'bug' in story.tags and 'confirmed' not in story.tags and\
            story.status.lower() == 'active':
            return True
        return False

    def is_open_task(self, task):
        # find unassigned tasks in todo status from stories in project group
        # that are tagged "groomed" (assumed), not tagged "blocked"
        if task.status.lower() == "todo" and task.assignee_id == None:
            if "blocked" not in self.client.stories.get(id=task.story_id).tags:
                return True
        return False

    def is_blocked_task(self, task):
        # find tasks from stories in project group that are tagged "blocked"
        if "blocked" in self.client.stories.get(id=task.story_id).tags:
            return True
        return False

    def is_open_confirmed_bug(self, task):
        # find unassigned tasks in todo status from stories in project
        # group that are tagged "bug" & "confirmed"
        if task.status.lower() == "todo" and task.assignee_id == None:
            if set(["bug", "confirmed"]) in\
            set(self.client.stories.get(id=task.story_id).tags):
                return True
        return False

    def is_current_sprint(self, task):
        # find assigned tasks in todo status from stories in project group
        # that are tagged "groomed" or ("bug" & "confirmed")
        if task.status.lower() == "todo" and task.assignee_id != None:
            return True
        return False

    # Lanes In Progress, In Review can be managed automatically
    def is_done_during_sprint(self, task):
        # tasks in project groups that were set as "Done"
        # before current due date, after previous one 
        if task.status.lower() == "merged":
            # assume last update was setting status to "merged"
            sprint_start, sprint_end = self.get_sprint_boundaries()
            if sprint_start.date < task.updated_at < sprint_end.date:
                return True
        return False       

    def set_due_date_for_sprint(self, sprint_name):
        # Assume sprints are named as %Y-%W (year-week number, for example
        # 2017-12) and end on the Friday of that week.
        sprint_end = datetime.datetime.strptime(
            sprint_name,'%Y-%W-%w').strftime('%Y-%m-%dT23:59:00+00:00')
        self.client.due_dates.create(name=sprint_name, date=sprint_end,
                                     board_id=self.board_id)

    def clean_groom_worklist(self):
        # remove stories tagged "groomed", or status not 'active'
        for story in self.client.worklists.get(id=self.groom_worklist.id).items:
            s = self.client.stories.get(story['item_id'])
            if not self.is_to_groom(s):
                self.move_to_lane(s, 'story')

    def clean_bug_worklist(self):
        # remove stories tagged "confirmed", or status not 'active'
        for story in self.client.worklists.get(id=self.bug_worklist.id).items:
            s = self.client.stories.get(story['item_id'])
            if not self.is_to_triage(s):
                self.move_to_lane(s, 'story')

    def clean_sprint_board(self):
        # Groomed Stories
        for story in self.client.worklists.get(self.board_lanes['Groomed Stories'].id).items:
            s = self.client.stories.get(story['item_id'])
            if s.status.lower() != 'active':
                self.move_to_lane(s, 'story')
        # Open Tasks
        for task in self.client.worklists.get(self.board_lanes['Open Tasks'].id).items:
            t = self.client.tasks.get(task['item_id'])
            if t.status.lower() != 'todo' or t.assignee_id is not None:
                self.move_to_lane(t, 'task')
        # Open Confirmed Bugs
        for task in self.client.worklists.get(self.board_lanes['Open Confirmed Bugs'].id).items:
            t = self.client.tasks.get(task['item_id'])
            if not self.is_open_confirmed_bug(t):
                self.move_to_lane(t, 'task')
        # Blocked
        for task in self.client.worklists.get(self.board_lanes['Blocked'].id).items:
            t = self.client.tasks.get(task['item_id'])
            if not self.is_blocked(t):
                self.move_to_lane(t, 'task')
        # Current Sprint
        for task in self.client.worklists.get(self.board_lanes['Current Sprint'].id).items:
            t = self.client.tasks.get(task['item_id'])
            if not self.is_current_sprint(t):
                self.move_to_lane(t, 'task')

    def update_boards(self):
        # TODO remove all items from worklists first
        for story in self.stories:
            print "Checking Story #%s..." % story.id
            if self.is_to_triage(story):
                # move to bug_worklist
                print "Story #%s goes to bug triage" % story.id
                self.move_to_lane(story, 'story', self.bug_worklist.id)
            elif self.is_to_groom(story):
                # move to groom_worklist
                print "Story #%s goes to grooming" % story.id
                self.move_to_lane(story, 'story', self.groom_worklist.id)
            else:
                if story.status.lower() == 'active':
                    self.move_to_lane(story, 'story',
                                      self.board_lanes['Groomed Stories'].id)
                    print "Story is groomed and active, checking tasks..."
                for task in story.tasks.get_all():
                    print "Checking task #%s" % task.id
                    if self.is_blocked_task(task):
                        # move to lane 'Blocked'
                        print "Task #%s (story #%s) is blocked" % (task.id,
                                                                   story.id)
                        self.move_to_lane(task, 'task',
                                          self.board_lanes['Blocked'].id)
                    elif self.is_open_confirmed_bug(task):
                        # move to lane 'Open Confirmed Bugs'
                        msg = "Task #%s (story #%s) is an open, confirmed bug"
                        msg = msg % (task.id, story.id)
                        print msg
                        self.move_to_lane(task, 'task',
                            self.board_lanes['Open Confirmed Bugs'].id)
                    elif self.is_open_task(task):
                        # move to lane 'Open Tasks'
                        print "Task #%s (story #%s) is an open task" % (task.id, story.id)
                        self.move_to_lane(task, 'task', self.board_lanes['Open Tasks'].id)
                    elif self.is_current_sprint(task):
                        # move to lane 'Current Sprint'
                        print "Task #%s (story #%s) is in the current sprint" % (task.id, story.id)
                        self.move_to_lane(task, 'task', self.board_lanes['Current Sprint'].id)
                    elif self.is_done_during_sprint(task):
                        # move to lane 'Done'
                        print "Task #%s (story #%s) is done" % (task.id, story.id)
                        self.move_to_lane(task, 'task', self.board_lanes['Done'].id)
                    else:
                        print 'Could not sort task #%s "%s" into a lane' % (task.id, task.title)


def main():
    # common args
    parser = argparse.ArgumentParser(description="SF scrum master")
    parser.add_argument('--url', '-u', metavar='https://sf.dom',
                        help='The URL of your SF instance')
    parser.add_argument('--api-key', '-a', metavar='APIKEY',
                        help=('API key to use to perform these operations.'
                              'The user should be authorized for these'))
    parser.add_argument('--project-group', '-p', metavar='project-group',
                        help='The project group for which operations are done')
    commands = parser.add_subparsers(dest="command")

    # boards commands
    boards_parser = commands.add_parser('boards')
    boards_subcmd = boards_parser.add_subparsers(dest='subcommand')
    update_boards = boards_subcmd.add_parser('update',
                                             help='Update boards lanes '
                                                  '& worklists')
    update_boards.add_argument('--board', metavar='BOARD', default='sf-sprint',
                               help='The board to use')
    update_boards.add_argument('--bug-worklist', metavar='BUG-WORKLIST',
                               default='sf-bug-triage',
                               help='The worklist to use for bug triage')
    update_boards.add_argument('--unrefined-worklist',
                               metavar='UNREFINED-WORKLIST',
                               default='sf-unrefined-stories',
                               help='The bug worklist to use')
    clean_boards = boards_subcmd.add_parser('clean',
                                            help='Remove tasks and stories '
                                                 'that do not belong in boards'
                                                 ' lanes & worklists')
    clean_boards.add_argument('--board', metavar='BOARD', default='sf-sprint',
                              help='The board to use')
    clean_boards.add_argument('--bug-worklist', metavar='BUG-WORKLIST',
                              default='sf-bug-triage',
                              help='The worklist to use for bug triage')
    clean_boards.add_argument('--unrefined-worklist',
                              metavar='UNREFINED-WORKLIST',
                              default='sf-unrefined-stories',
                              help='The bug worklist to use')
    # sprint commands
    sprint_parser = commands.add_parser('sprint')
    sprint_subcmd = sprint_parser.add_subparsers(dest='subcommand')
    start_sprint = sprint_subcmd.add_parser('start',
                                            help='Start a new sprint')
    start_sprint.add_argument('sprint_name', metavar='SPRINT_NAME',
                              help='The name of the sprint')
    start_sprint.add_argument('--board', '-b', metavar='BOARD',
                              default='sf-backlog-ng',
                              help='The board to use')
    close_sprint = sprint_subcmd.add_parser('close',
                                            help='Close a sprint')
    close_sprint.add_argument('sprint_name', metavar='SPRINT_NAME',
                              help='The name of the sprint')
    summary_sprint = sprint_subcmd.add_parser('summary',
                                              help='Generate a summary '
                                                   'of a sprint')

    args = parser.parse_args()

    if args.command == 'boards':
        manager = StoryboardManager(args.url, args.api_key,
                                    args.project_group, args.board,
                                    args.unrefined_worklist,
                                    args.bug_worklist)
        if args.subcommand == 'update' or args.subcommand =='clean':
            manager.clean_groom_worklist()
            manager.clean_bug_worklist()
            manager.clean_sprint_board()
        if args.subcommand == 'update':
            manager.update_boards()
    elif args.command == 'sprint':
        manager = StoryboardManager(self, args.url, args.api_key,
                                    args.project_group, args.board)
        if args.subcommand == 'start':
            manager.set_due_date_for_sprint(args.sprint_name)
            # TODO remove Done stories tagged with previous sprint
        elif args.subcommand == 'close':
            # TODO
            pass
    else:
        print "Command not supported."
        sys.exit(1)

if __name__ == "__main__":
    main()
