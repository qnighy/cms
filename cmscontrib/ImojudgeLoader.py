#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# Programming contest management system
# Copyright © 2010-2013 Giovanni Mascellani <mascellani@poisson.phc.unipi.it>
# Copyright © 2010-2012 Stefano Maggiolo <s.maggiolo@gmail.com>
# Copyright © 2010-2012 Matteo Boscariol <boscarim@hotmail.com>
# Copyright © 2013 Luca Wehrstedt <luca.wehrstedt@gmail.com>
# Copyright © 2013 Masaki Hara <ackie.h.gmai@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import io
import os
import os.path
import yaml
import simplejson as json
import re
import pytz
from datetime import datetime, tzinfo
import calendar
import zipfile

from datetime import timedelta

from cms import LANGUAGES, logger

from cms.db.SQLAlchemyAll import \
    Contest, User, Task, Statement, Attachment, SubmissionFormatElement, \
    Dataset, Manager, Testcase
from cmscontrib.BaseLoader import Loader
from cmscontrib import touch


def load(src, dst, src_name, dst_name=None, conv=lambda i: i):
    if dst_name is None:
        dst_name = src_name
    if src_name in src:
        dst[dst_name] = conv(src[src_name])


def make_datetime_tz(timezone):
    def make_datetime(timestring):
        """Return the datetime object associated with the given timestamp

        timezone (tzinfo): timezone
        timestring (string): datetime string with format "%Y/%m/%d %H:%M:%S"
        returns (datetime): the datetime representing the UTC time of the
                            given timestamp, or now if timestamp is None.

        """
        local_time = datetime.strptime(timestring, "%Y/%m/%d %H:%M:%S")
        local_time = timezone.localize(local_time)
        return local_time.astimezone(pytz.utc).replace(tzinfo=None)
    return make_datetime


def make_timedelta(t):
    return timedelta(seconds=t)


class ImojudgeLoader(Loader):

    """Load a contest stored using the Italian IOI format.

    Given the filesystem location of a contest saved in the Italian IOI
    format, parse those files and directories to produce data that can
    be consumed by CMS, i.e. a hierarchical collection of instances of
    the DB classes, headed by a Contest object, and completed with all
    needed (and available) child objects.

    """

    short_name = 'imojudge'
    description = 'Imojudge-like format'

    @classmethod
    def detect(cls, path):
        """See docstring in class Loader.

        """
        # Not really refined...
        return os.path.exists(os.path.join(path, "contest-imoj.yaml"))

    def get_contest(self):

        """Produce a Contest object.

        Do what is needed (i.e. search directories and explore files
        in the location given to the constructor) to produce a Contest
        object. Also get a minimal amount of information on users and
        tasks, at least enough to produce two lists of dicts, one for
        each user/task in the contest, containing the username/user and
        every other information you think is useful. These dicts will
        then be given as arguments to get_user/get_task that have to
        produce fully-featured User/Task objects.

        return (tuple): Contest object and two lists of dicts. Each
                        element of the first list has to contain a
                        "username" item whereas the ones in the second
                        have to contain a "name" item.

        """

        conf = yaml.safe_load(
            io.open(os.path.join(self.path, "contest-imoj.yaml"),
                    "rt", encoding="utf-8"))


        logger.info("Loading parameters for contest %s." % conf["name"])

        self.auto_attach = conf.get("auto_attach", False)

        args = {}

        load(conf, args, "name")
        load(conf, args, "description")
        load(conf, args, "timezone")

        name = args["name"]

        try:
            timezone = pytz.timezone(args["timezone"])
        except:
            timezone = pytz.utc

        load(conf, args, "token_initial")
        load(conf, args, "token_max")
        load(conf, args, "token_total")
        load(conf, args, "token_min_interval", conv=make_timedelta)
        load(conf, args, "token_gen_time", conv=make_timedelta)
        load(conf, args, "token_gen_number")

        load(conf, args, "start", conv=make_datetime_tz(timezone))
        load(conf, args, "stop", conv=make_datetime_tz(timezone))

        load(conf, args, "max_submission_number")
        load(conf, args, "max_user_test_number")
        load(conf, args, "min_submission_interval", conv=make_timedelta)
        load(conf, args, "min_user_test_interval", conv=make_timedelta)

        logger.info("Contest parameters loaded.")

        for i, v in enumerate(conf["users"]):
            conf["users"][i]["num"] = i

        for i, v in enumerate(conf["tasks"]):
            conf["tasks"][i]["num"] = i

        tasks = [x["name"] for x in conf["tasks"]]
        users = [x["username"] for x in conf["users"]]

        self.tasks_conf = dict((x["name"],x) for x in conf["tasks"])
        self.users_conf = dict((x["username"],x) for x in conf["users"])

        return Contest(**args), tasks, users

    def has_changed(self, name):
        """See docstring in class Loader

        """

        metainfo_filename = os.path.join(self.path,
                self.tasks_conf[name]["dir"], ".metainfo")

        if not os.path.exists(metainfo_filename):
            return True

        metainfo_new = self.collect_metainfo(name)
        with open(metainfo_filename, "r") as metainfo_file:
            metainfo_old = json.load(metainfo_file)

        return metainfo_new != metainfo_old

    def collect_metainfo(self, name):

        conf = self.tasks_conf[name]
        assert name == conf["name"]

        dirname = conf["dir"]
        num = conf["num"]

        task_path = os.path.join(self.path, dirname)

        # Generate a task's list of files
        # Testcases
        files = []
        if os.path.exists(os.path.join(task_path, "in")):
            for filename in os.listdir(os.path.join(task_path, "in")):
                files.append(os.path.join(task_path, "in", filename))

        if os.path.exists(os.path.join(task_path, "out")):
            for filename in os.listdir(os.path.join(task_path, "out")):
                files.append(os.path.join(task_path, "out", filename))

        # Score file
        files.append(os.path.join(task_path, "etc", "score.txt"))

        # Statement
        if os.path.exists(os.path.join(task_path, "task")):
            for filename in os.listdir(os.path.join(task_path, "task")):
                files.append(os.path.join(task_path, "task", filename))

        # Managers
        files.append(os.path.join(task_path, "cms", "checker"))
        files.append(os.path.join(task_path, "cms", "manager"))
        for lang in LANGUAGES:
            files.append(os.path.join(task_path, "cms", "grader.%s" % lang))
        if os.path.exists(os.path.join(task_path, "cms")):
            for other_filename in os.listdir(os.path.join(task_path, "cms")):
                if other_filename.endswith('.h') or \
                        other_filename.endswith('lib.pas'):
                    files.append(os.path.join(task_path, "sol", other_filename))

        mtimes = []

        for fname in sorted(files):
            if os.path.exists(fname):
                mtimes.append([fname, os.stat(fname).st_mtime])

        return [conf, mtimes]

    def get_user(self, username):
        """See docstring in class Loader.

        """
        logger.info("Loading parameters for user %s." % username)
        conf = self.users_conf[username]
        assert username == conf['username']

        args = {}

        load(conf, args, "username")

        load(conf, args, "password")
        load(conf, args, "ip")

        load(conf, args, "first_name")
        load(conf, args, "last_name")

        if "first_name" not in args:
            args["first_name"] = ""
        if "last_name" not in args:
            args["last_name"] = args["username"]

        load(conf, args, "fake", "hidden", lambda a: a == "True")

        logger.info("User parameters loaded.")

        return User(**args)

    def get_task(self, name):
        """See docstring in class Loader.

        """
        conf = self.tasks_conf[name]
        assert name == conf["name"]

        dirname = conf["dir"]
        num = conf["num"]

        task_path = os.path.join(self.path, dirname)

        if not os.path.exists(task_path):
            raise Exception("Task directory %s does not exist." % task_path)

        logger.info("Loading parameters for task %s." % name)

        args = {}

        args["num"] = num
        load(conf, args, "name")
        load(conf, args, "title")

        if args["name"] == args["title"]:
            logger.warning("Short name equals long name (title). "
                           "Please check.")

        args["statements"] = []

        if os.path.exists(os.path.join(task_path, "task")):
            for f in os.listdir(os.path.join(task_path, "task")):
                m = re.match(r'task-([a-z]+).pdf$', f)
                if m:
                    lang = m.group(1)
                    digest = self.file_cacher.put_file(
                        path=os.path.join(task_path, "task", f),
                        description="Statement for task %s (lang: %s)"
                        % (name, lang))
                    args["statements"] += [Statement(lang, digest)]
        else:
            logging.warning("Task statement directory %s/task does not exist."
                    % task_path)

        args["primary_statements"] = '["ja"]'

        args["attachments"] = []

        if conf.get("auto_attach", self.auto_attach) == True:
            if not os.path.exists(os.path.join(task_path, "attach")):
                os.mkdir(os.path.join(task_path, "attach"))
            archive = zipfile.ZipFile(os.path.join(task_path, "attach", \
                    name+".zip"), "w", zipfile.ZIP_DEFLATED)
            if os.path.exists(os.path.join(task_path, "sample")):
                for filename in os.listdir(os.path.join(task_path, "sample")):
                    archive.write(os.path.join(task_path, "sample", filename), \
                            os.path.join(name, filename))
            if os.path.exists(os.path.join(task_path, "dist")):
                for filename in os.listdir(os.path.join(task_path, "dist")):
                    archive.write(os.path.join(task_path, "dist", filename), \
                            os.path.join(name, filename))
            archive.close()

        if os.path.exists(os.path.join(task_path, "attach")):
            for filename in os.listdir(os.path.join(task_path, "attach")):
                attach_digest = self.file_cacher.put_file(
                    path=os.path.join(task_path, "attach", filename),
                    description="Attachment for task %s" % name)
                args["attachments"].append(Attachment(
                        filename,
                        attach_digest))

        args["submission_format"] = [
            SubmissionFormatElement("%s.%%l" % name)]

        load(conf, args, "token_initial")
        load(conf, args, "token_max")
        load(conf, args, "token_total")
        load(conf, args, "token_min_interval", conv=make_timedelta)
        load(conf, args, "token_gen_time", conv=make_timedelta)
        load(conf, args, "token_gen_number")

        load(conf, args, "max_submission_number")
        load(conf, args, "max_user_test_number")
        load(conf, args, "min_submission_interval", conv=make_timedelta)
        load(conf, args, "min_user_test_interval", conv=make_timedelta)

        task = Task(**args)

        args = {}
        args["task"] = task
        args["description"] = conf.get("version", "Default")
        args["autojudge"] = False

        load(conf, args, "time_limit", conv=float)
        load(conf, args, "memory_limit")

        # Builds the parameters that depend on the task type
        args["managers"] = []
        infile_param = conf.get("infile", "")
        outfile_param = conf.get("outfile", "")

        args["task_type"] = conf.get("task_type", "Batch")

        # If there is cms/grader.%l for some language %l, then,
        # presuming that the task type is Batch, we retrieve graders
        # in the form cms/grader.%l
        graders = False
        for lang in LANGUAGES:
            if os.path.exists(os.path.join(
                    task_path, "cms", "grader.%s" % lang)):
                graders = True
                break
        if graders:
            # Read grader for each language
            for lang in LANGUAGES:
                grader_filename = os.path.join(
                    task_path, "cms", "grader.%s" % lang)
                if os.path.exists(grader_filename):
                    digest = self.file_cacher.put_file(
                        path=grader_filename,
                        description="Grader for task %s and language %s" %
                                    (name, lang))
                    args["managers"] += [
                        Manager("grader.%s" % lang, digest)]
                else:
                    logger.error("Grader for language %s not found " % lang)
            compilation_param = "grader"
        else:
            compilation_param = "alone"

        if os.path.exists(os.path.join(task_path, "cms")):
            # Read managers with other known file extensions
            for other_filename in os.listdir(os.path.join(task_path, "cms")):
                if other_filename.endswith('.h') or \
                        other_filename.endswith('lib.pas'):
                    digest = self.file_cacher.put_file(
                        path=os.path.join(task_path, "cms", other_filename),
                        description="Manager %s for task %s" %
                                    (other_filename, name))
                    args["managers"] += [
                        Manager(other_filename, digest)]

        # If there is cms/checker, we retrieve the comparator
        if os.path.exists(os.path.join(task_path, "cms", "checker")):
            digest = self.file_cacher.put_file(
                path=os.path.join(task_path, "cms", "checker"),
                description="Checker for task %s" % name)
            args["managers"] += [
                Manager("checker", digest)]
            evaluation_param = "comparator"
        else:
            evaluation_param = "diff"
            if args["task_type"] == "OutputOnly":
                logger.warning("output checker not found")

        testfiles = []
        testfile_meta = {}

        for testfile_real in os.listdir(os.path.join(task_path, "in")):
            testfile = testfile_real.replace(".txt", "")
            testfiles.append(testfile)
            testfile_meta[testfile] = [testfile_real, False]
        testfiles.sort()

        scoretxt_filename = os.path.join(task_path, 'etc', 'score.txt')
        try:
            with open(scoretxt_filename) as scoretxt_file:

                testgroups = []

                feedbacks_wc = None
                for line in scoretxt_file:
                    line = line.strip()
                    splitted = line.split(':', 2)

                    if len(splitted) == 1:
                        raise Exception("There should be at least "
                                "one ':' sign.")

                    elif splitted[0].strip()=="Feedback":
                        if feedbacks_wc:
                            raise Exception("There should be only one "
                                    "Feedback line.")
                        feedbacks_wc = splitted[1].split(',')
                    else:
                        group_matched = re.match(
                                r'([0-9a-zA-Z_ ]+)\(\s*(\d+)\s*\)\s*\Z',
                                splitted[0])
                        if not group_matched:
                            raise Exception("malformed score.txt")
                        group_name, group_score = group_matched.groups()
                        files_wc = splitted[1].split(',')
                        testgroup = []
                        for file_wc in files_wc:
                            file_r = re.compile(
                                    file_wc.strip().replace("*", ".*")+r'\Z')
                            for i, testfile in enumerate(testfiles):
                                if file_r.match(testfile):
                                    testgroup.append(i)

                        testgroups.append({'name':group_name,
                            'files':testgroup, 'score':float(group_score),
                            'type':'min'})

                assert(100 == sum([int(st['score']) for st in testgroups]))
                args["score_type"] = "NamedGroup"
                args["score_type_parameters"] = json.dumps(
                        {'testfiles':testfiles, 'testgroups':testgroups})
                if feedbacks_wc:
                    for feedback_wc in feedbacks_wc:
                        feedback_r = re.compile(
                                feedback_wc.strip().replace("*", ".*")+r'\Z')
                        for testfile in testfiles:
                            if feedback_r.match(testfile):
                                testfile_meta[testfile][1] = True
                else:
                    raise Exception("There should be one Feedback line.")

        except IOError:
            logger.warning("score.txt does not exist")
            testgroups = []
            for i, testfile in enumerate(testfiles):
                testgroups.append({'name':testfile,
                    'files':[i], 'score':float(100.0/len(testfiles)),
                    'type':'min'})
                testfile_meta[testfile][1] = True
            args["score_type"] = "NamedGroup"
            args["score_type_parameters"] = json.dumps(
                    {'testfiles':testfiles, 'testgroups':testgroups})

        if args["task_type"] == "OutputOnly":
            args["time_limit"] = None
            args["memory_limit"] = None
            args["task_type_parameters"] = json.dumps([evaluation_param,
                ["%s.txt" % x for x in testfiles]])
            task.submission_format = [
                SubmissionFormatElement("%s.txt" % x)
                for x in testfiles]

        elif args["task_type"] == "Communication":
            args["task_type_parameters"] = json.dumps('[]')
            if os.path.exists(os.path.join(task_path, "cms", "manager")):
                digest = self.file_cacher.put_file(
                    path=os.path.join(task_path, "cms", "manager"),
                    description="Manager for task %s" % name)
            else:
                logger.error("Manager for task %s not found " % name)
            args["managers"] += [
                Manager("manager", digest)]
            for lang in LANGUAGES:
                stub_name = os.path.join(task_path, "cms", "stub.%s" % lang)
                if os.path.exists(stub_name):
                    digest = self.file_cacher.put_file(
                        path=stub_name,
                        description="Stub for task %s and language %s" %
                                    (name, lang))
                    args["managers"] += [
                        Manager("stub.%s" % lang, digest)]
                else:
                    logger.error("Stub for language %s not found." % lang)

        elif args["task_type"] == "Communication2":
            args["task_type_parameters"] = '[]'
            args["submission_format"] = [
                SubmissionFormatElement(f)
                for f in conf["submission_format"]]
            digest = self.file_cacher.put_file(
                path=os.path.join(task_path, "cms", "manager"),
                description="Manager for task %s" % name)
            args["managers"] += [
                Manager("manager", digest)]
            for lang in LANGUAGES:
                stub_name = os.path.join(task_path, "cms", "stub.%s" % lang)
                if os.path.exists(stub_name):
                    digest = self.file_cacher.put_file(
                        path=stub_name,
                        description="Stub for task %s and language %s" %
                                    (name, lang))
                    args["managers"] += [
                        Manager("stub.%s" % lang, digest)]
                else:
                    logger.error("Stub for language %s not found." % lang)

        # Otherwise, the task type is Batch
        else:
            args["task_type"] = "Batch"
            args["task_type_parameters"] = \
                '["%s", ["%s", "%s"], "%s"]' % \
                (compilation_param, infile_param, outfile_param,
                 evaluation_param)

        args["testcases"] = []
        for num, testfile in enumerate(testfiles):
            testfile_real = testfile_meta[testfile][0]
            _input = os.path.join(task_path, "in", testfile_real)
            output = os.path.join(task_path, "out", testfile_real)
            input_digest = self.file_cacher.put_file(
                path=_input,
                description="Input %s for task %s" % (testfile, name))
            if os.path.exists(output):
                output_digest = self.file_cacher.put_file(
                    path=output,
                    description="Output %s for task %s" % (testfile, name))
            else:
                logger.error("output file %s does not exist" % output)
                output_digest = ""
            args["testcases"].append(Testcase(
                num=num,
                public=testfile_meta[testfile][1],
                input=input_digest,
                output=output_digest))
            if args["task_type"] == "OutputOnly":
                task.attachments += [Attachment(
                        "%s.txt" % testfiles[num],
                        input_digest)]

        dataset = Dataset(**args)
        task.active_dataset = dataset

        with open(os.path.join(task_path, ".metainfo"), "w") as metainfo_file:
            json.dump(self.collect_metainfo(name), metainfo_file)

        logger.info("Task parameters loaded.")

        return task

