#!/usr/bin/env python

import argparse
import datetime
from six.moves.urllib.parse import urljoin
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
    def __init__(self, url, api_key, project_group, board):
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

    def find_current_lane(self, item, type):
        lanes = self.board_lanes.values()
        for lane in lanes:
            for i in lane.items:
                if (i['item_type'] == type and i['item_id'] == item.id and
                   not i['archived']):
                    return lane.id, i['id']
        return None, None

    def move_to_lane(self, item, type, lane_id=None):
        """Move item of type (story or task) to worklist lane_id."""
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

    def remove_from_lane(self, item, id_in_lane, lane_id):
        print "removing task %s from %s" % (item.id, lane_id)
        r = self.client.delete("worklists/%s/items/" % lane_id,
                               json=dict(item_id=id_in_lane))
        print "del %s" % r.status_code

    def get_sprint_boundaries(self):
        due_dates = self.client.due_dates.get_all(board_id=self.board_id)
        return sorted(due_dates, key=lambda x: x.date)[-2:]

    # worklists operations
    def is_to_groom(self, story, regroom_after=None):
        # find stories in project group that are untagged, unassigned,
        # in status "Todo"
        if 'groomed' in story.tags:
            if regroom_after:
                delta = datetime.timedelta(days=regroom_after)
                last_update = datetime.datetime.strptime(
                    story.updated_at,
                    '%Y-%m-%dT%H:%M:%S+00:00')
                if datetime.datetime.now() - last_update > delta:
                    return True
            return False
        else:
            if any(t.status.lower() != 'todo' for t in story.tasks.get_all()):
                return False
            else:
                return True

    def is_to_triage(self, story):
        # find stories in project group that are tagged "bug"
        # but not tagged "confirmed"
        if ('bug' in story.tags and 'confirmed' not in story.tags and
           story.status.lower() == 'active'):
            return True
        return False

    def is_open_task(self, task):
        # find unassigned tasks in todo status from stories in project group
        # that are tagged "groomed" (assumed), not tagged "blocked"
        if task.status.lower() == "todo" and task.assignee_id is None:
            if "blocked" not in self.client.stories.get(id=task.story_id).tags:
                return True
        return False

    def is_blocked_task(self, task):
        # find tasks from stories in project group that are tagged "blocked"
        if "blocked" in self.client.stories.get(id=task.story_id).tags:
            if task.status.lower() not in ['merged', 'invalid']:
                return True
        return False

    def is_open_confirmed_bug(self, task):
        # find unassigned tasks in todo status from stories in project
        # group that are tagged "bug" & "confirmed"
        if task.status.lower() == "todo" and task.assignee_id is None:
            tags = self.client.stories.get(id=task.story_id).tags
            tags_set = [u.lower() for u in tags]
            if "bug" in tags_set and "confirmed" in tags_set:
                return True
        return False

    def is_current_sprint(self, task):
        # find assigned tasks in todo status from stories in project group
        # that are tagged "groomed" or ("bug" & "confirmed")
        if task.status.lower() == "todo" and task.assignee_id is not None:
            return True
        return False

    # Lanes In Progress, In Review are managed automatically
    def is_in_progress(self, task):
        if task.status.lower() == "progress":
            return True
        return False

    def is_in_review(self, task):
        if task.status.lower() == "review":
            return True
        return False

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
        prev_start, prev_end = self.get_sprint_boundaries()
        end = sprint_name + "-5"
        sprint_end = datetime.datetime.strptime(
            end, '%Y-%W-%w').strftime('%Y-%m-%dT23:59:00+00:00')
        if prev_end.date == sprint_end:
            print "End date already set"
            return
        self.client.due_dates.create(name=sprint_name, date=sprint_end,
                                     board_id=self.board_id)

    def clean_sprint_board(self):
        # Groomed Stories
        print "Clean groomed stories..."
        lane_id = self.board_lanes['Groomed Stories'].id
        for story in self.client.worklists.get(lane_id).items:
            if story['archived']:
                continue
            s = self.client.stories.get(story['item_id'])
            if "groomed" not in s.tags:
                self.remove_from_lane(s, story['id'], lane_id)
            elif s.status.lower() != 'active':
                self.remove_from_lane(s, story['id'], lane_id)
        # Open Tasks
        print "Clean open tasks..."
        lane_id = self.board_lanes['Open Tasks'].id
        for task in self.client.worklists.get(lane_id).items:
            if task['archived']:
                continue
            try:
                t = self.client.tasks.get(task['item_id'])
                if t.status.lower() != 'todo' or t.assignee_id is not None:
                    self.remove_from_lane(t, task['id'], lane_id)
            except exceptions.NotFound:
                print 'Error: Task "%s" not found' % task
        # Open Confirmed Bugs
        print "Clean confirmed bugs..."
        lane_id = self.board_lanes['Open Confirmed Bugs'].id
        for task in self.client.worklists.get(lane_id).items:
            if task['archived']:
                continue
            try:
                t = self.client.tasks.get(task['item_id'])
                if not self.is_open_confirmed_bug(t):
                    self.remove_from_lane(t, task['id'], lane_id)
            except exceptions.NotFound:
                print 'Error: Task "%s" not found' % task
        # Blocked
        print "Clean blocked..."
        lane_id = self.board_lanes['Blocked'].id
        for task in self.client.worklists.get(lane_id).items:
            if task['archived']:
                continue
            try:
                t = self.client.tasks.get(task['item_id'])
                if not self.is_blocked_task(t):
                    self.remove_from_lane(t, task['id'], lane_id)
            except exceptions.NotFound:
                print 'Error: Task "%s" not found' % task
        # Current Sprint
        print "Clean current sprint..."
        lane_id = self.board_lanes['Current Sprint'].id
        for task in self.client.worklists.get(lane_id).items:
            if task['archived']:
                continue
            try:
                t = self.client.tasks.get(task['item_id'])
                if not self.is_current_sprint(t):
                    self.remove_from_lane(t, task['id'], lane_id)
            except exceptions.NotFound:
                print 'Error: Task "%s" not found' % task

    def update_boards(self):
        # TODO remove all items from worklists first
        for story in self.stories:
            print "Checking Story #%s... " % story.id,
            if self.is_to_triage(story):
                print "To triage"
                continue
            if self.is_to_groom(story):
                print "To groom"
                continue
            if story.status.lower() != 'active':
                print story.status
                continue
            else:
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
                        lane_id = self.board_lanes['Open Confirmed Bugs'].id
                        self.move_to_lane(task, 'task', lane_id)
                    elif self.is_open_task(task):
                        # move to lane 'Open Tasks'
                        msg = "Task #%s (story #%s) is an open task"
                        print msg % (task.id, story.id)
                        self.move_to_lane(task, 'task',
                                          self.board_lanes['Open Tasks'].id)
                    elif self.is_current_sprint(task):
                        # move to lane 'Current Sprint'
                        lane = 'Current Sprint'
                        msg = "Task #%s (story #%s) is in the current sprint"
                        print msg % (task.id, story.id)
                        self.move_to_lane(task, 'task',
                                          self.board_lanes[lane].id)
                    elif self.is_done_during_sprint(task):
                        # move to lane 'Done'
                        msg = "Task #%s (story #%s) is done"
                        print msg % (task.id, story.id)
                        self.move_to_lane(task, 'task',
                                          self.board_lanes['Done'].id)
                    else:
                        msg = 'Could not sort task #%s "%s" into a lane'
                        print msg % (task.id, task.title)

    def tag_task(self, task, tag):
        story = self.client.stories.get(task.story_id)
        if tag in story.tags:
            # Nothing to do
            return 200
        r = self.client.put("tags/%s" % task.story_id, json=[tag, ])
        return r.status_code

    def get_summary(self):
        sprint_start, sprint_end = self.get_sprint_boundaries()
        in_progress = []
        summary = {'done': [],
                   'in progress': {},
                   'new': []}
        for story in self.stories:
            if sprint_start.date < story.updated_at < sprint_end.date:
                if self.is_to_groom(story):
                    summary['new'].append(story)
                elif self.is_to_triage(story):
                    summary['new'].append(story)
                elif story.status.lower() == 'merged':
                    summary['done'].append(story)
                else:
                    in_progress.append(story)
        for story in in_progress:
            m = {'done': {'in': [], 'out': []},
                 'in review': {'in': [], 'out': []},
                 'in progress': {'in': [], 'out': []},
                 'to do': [],
                 'unassigned': []}
            for task in story.tasks.get_all():
                if task.status.lower() == 'merged':
                    if sprint_start.date < task.updated_at < sprint_end.date:
                        m['done']['in'].append(task)
                    else:
                        m['done']['out'].append(task)
                elif task.status.lower() == 'review':
                    if sprint_start.date < task.updated_at < sprint_end.date:
                        m['in review']['in'].append(task)
                    else:
                        m['in review']['out'].append(task)
                elif task.status.lower() == 'progress':
                    if sprint_start.date < task.updated_at < sprint_end.date:
                        m['in progress']['in'].append(task)
                    else:
                        m['in progress']['out'].append(task)
                elif task.status.lower() == 'todo':
                    if task.assignee_id is None:
                        m['unassigned'].append(task)
                    else:
                        m['to do'].append(task)
            summary['in progress'][story] = m
        return summary


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
    parser.add_argument('--board', '-b', metavar='BOARD',
                        default='sf-backlog-ng',
                        help='The board to use')
    commands = parser.add_subparsers(dest="command")

    # boards commands
    boards_parser = commands.add_parser('boards')
    boards_subcmd = boards_parser.add_subparsers(dest='subcommand')
    boards_subcmd.add_parser('update', help='Update boards lanes & worklists')
    boards_subcmd.add_parser('clean',
                             help='Remove tasks and stories '
                                  'that do not belong in boards lanes')
    # sprint commands
    sprint_parser = commands.add_parser('sprint')
    sprint_subcmd = sprint_parser.add_subparsers(dest='subcommand')
    start_sprint = sprint_subcmd.add_parser('start',
                                            help='Start a new sprint')
    start_sprint.add_argument('sprint_name', metavar='SPRINT_NAME',
                              help='The name of the sprint')
    close_sprint = sprint_subcmd.add_parser('close',
                                            help='Close a sprint')
    close_sprint.add_argument('sprint_name', metavar='SPRINT_NAME',
                              help='The name of the sprint')
    sprint_subcmd.add_parser('summary',
                             help='Generate a summary of current sprint')

    args = parser.parse_args()
    manager = StoryboardManager(args.url, args.api_key,
                                args.project_group, args.board)

    if args.command == 'boards':
        if args.subcommand == 'update' or args.subcommand == 'clean':
            manager.clean_sprint_board()
        if args.subcommand == 'update':
            manager.update_boards()
    elif args.command == 'sprint':
        if args.subcommand == 'start':
            manager.set_due_date_for_sprint(args.sprint_name)
            # Done stories that weren't modified after sprint start
            start, finish = manager.get_sprint_boundaries()
            msg = "Cleaning tasks for new sprint %s (%s -> %s)..."
            print msg % (args.sprint_name, start.date, finish.date)
            done_id = manager.board_lanes['Done'].id
            for task in manager.board_lanes['Done'].items:
                if 'archived' in task and not task['archived']:
                    t = manager.client.tasks.get(id=task['item_id'])
                    if t.updated_at < start.date:
                        manager.remove_from_lane(t, task['id'], done_id)
        elif args.subcommand == 'close':
            for lane in ['Current Sprint',
                         'In Progress',
                         'Ready for Review',
                         'Done']:
                for task in manager.board_lanes[lane].items:
                    if 'archived' in task and not task['archived']:
                        # we cannot tag tasks yet, so tag the story
                        t = manager.client.tasks.get(task['item_id'])
                        r = manager.tag_task(t, args.sprint_name)
                        if int(r) < 400:
                            print "#%s (%s) tagged %s" % (task['item_id'],
                                                          t.title,
                                                          args.sprint_name)
                        else:
                            print "could not tag #%s (%s)" % (task['item_id'],
                                                              t.title)
        elif args.subcommand == 'summary':
            summary = manager.get_summary()
            print "STORIES COMPLETED:"
            print "==================\n"
            for story in summary['done']:
                if "bug" in story.tags:
                    print "[BUG] ",
                print "#%s - %s" % (story.id, story.title)
            print "\n"
            print "STORIES IN PROGRESS:"
            print "====================\n"
            for story in summary['in progress']:
                story_title = ""
                if "bug" in story.tags:
                    story_title += "[BUG] "
                story_title += "#%s - %s" % (story.id, story.title)
                print story_title
                print "-"*len(story_title)
                for task in summary['in progress'][story]['done']['in']:
                    print "\t(DONE) #%s - %s" % (task.id, task.title)
                for task in summary['in progress'][story]['in review']['in']:
                    print "\t(IN REVIEW) #%s - %s" % (task.id, task.title)
                for task in summary['in progress'][story]['in progress']['in']:
                    print "\t(IN PROGRESS) #%s - %s" % (task.id, task.title)
                for task in summary['in progress'][story]['to do']:
                    print "\t(TO DO) #%s - %s" % (task.id, task.title)
                for task in summary['in progress'][story]['unassigned']:
                    print "\t(UNASSIGNED) #%s - %s" % (task.id, task.title)
            print "\n"
            print "STORIES ADDED:"
            print "==============\n"
            for story in summary['new']:
                if "bug" in story.tags:
                    print "[BUG] ",
                print "#%s - %s" % (story.id, story.title)
    else:
        print "Command not supported."
        sys.exit(1)

if __name__ == "__main__":
    main()
