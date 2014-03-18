#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# Programming contest management system
# Copyright © 2010-2013 Giovanni Mascellani <mascellani@poisson.phc.unipi.it>
# Copyright © 2010-2012 Stefano Maggiolo <s.maggiolo@gmail.com>
# Copyright © 2010-2012 Matteo Boscariol <boscarim@hotmail.com>
# Copyright © 2013-2014 Luca Wehrstedt <luca.wehrstedt@gmail.com>
# Copyright © 2014 Masaki Hara <ackie.h.gmai@gmail.com>
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

from __future__ import absolute_import
from __future__ import unicode_literals

import io
import json
import logging
import os
import os.path
import re
import sys
import tempfile
import yaml
import zipfile
from datetime import timedelta

from cms import LANGUAGES
from cmscommon.datetime import make_datetime
from cms.db import Contest, User, Task, Statement, Attachment, \
    SubmissionFormatElement, Dataset, Manager, Testcase
from cmscontrib.BaseLoader import Loader
from cmscontrib import touch


logger = logging.getLogger(__name__)


# Patch PyYAML to make it load all strings as unicode instead of str
# (see http://stackoverflow.com/questions/2890146).
def construct_yaml_str(self, node):
    return self.construct_scalar(node)
yaml.Loader.add_constructor("tag:yaml.org,2002:str", construct_yaml_str)
yaml.SafeLoader.add_constructor("tag:yaml.org,2002:str", construct_yaml_str)


def load(src, dst, src_name, dst_name=None, conv=lambda i: i):
    """Execute:
      dst[dst_name] = conv(src[src_name])
    with the following features:

      * If src_name is a list, it tries each of its element as
        src_name, stopping when the first one succedes.

      * If dst_name is None, it is set to src_name; if src_name is a
        list, dst_name is set to src_name[0] (_not_ the one that
        succedes).

      * By default conv is the identity function.

      * If dst is None, instead of assigning the result to
        dst[dst_name] (which would cast an exception) it just returns
        it.

      * If src[src_name] doesn't exist, the behavior is different
        depending on whether dst is None or not: if dst is None,
        conv(None) is returned; if dst is not None, nothing is done
        (in particular, dst[dst_name] is _not_ assigned to conv(None);
        it is not assigned to anything!).

    """
    if dst is not None and dst_name is None:
        if isinstance(src_name, list):
            dst_name = src_name[0]
        else:
            dst_name = src_name
    res = None
    found = False
    if isinstance(src_name, list):
        for this_src_name in src_name:
            try:
                res = src[this_src_name]
            except KeyError:
                pass
            else:
                found = True
                break
    else:
        if src_name in src:
            found = True
            res = src[src_name]
    if dst is not None:
        if found:
            dst[dst_name] = conv(res)
    else:
        return conv(res)


def make_timedelta(t):
    return timedelta(seconds=t)


class ImojudgeLoader(Loader):
    """Load a contest stored using the Imojudge-compatible format.
    """

    short_name = 'imojudge'
    description = 'Imojudge-compatible format'

    @classmethod
    def detect(cls, path):
        """See docstring in class Loader.

        """
        return os.path.exists(os.path.join(path, "contest-imoj.yaml"))

    def get_contest(self):
        """See docstring in class Loader.

        """

        name = os.path.split(self.path)[1]
        conf = yaml.safe_load(
            io.open(os.path.join(self.path, "contest-imoj.yaml"),
                    "rt", encoding="utf-8"))

        logger.info("Loading parameters for contest %s." % name)

        args = {}

        load(conf, args, "name")
        load(conf, args, "description")

        load(conf, args, "token_mode")
        load(conf, args, "token_max_number")
        load(conf, args, "token_min_interval", conv=make_timedelta)
        load(conf, args, "token_gen_initial")
        load(conf, args, "token_gen_number")
        load(conf, args, "token_gen_interval", conv=make_timedelta)
        load(conf, args, "token_gen_max")

        load(conf, args, "start", conv=make_datetime)
        load(conf, args, "stop", conv=make_datetime)

        load(conf, args, "max_submission_number")
        load(conf, args, "max_user_test_number")
        load(conf, args, "min_submission_interval", conv=make_timedelta)
        load(conf, args, "min_user_test_interval", conv=make_timedelta)

        load(conf, args, "languages")
        if "languages" in args:
            for l in args["languages"]:
                assert l in LANGUAGES

        logger.info("Contest parameters loaded.")

        for num, task in enumerate(conf["tasks"]):
            task["num"] = num

        self.tasks_conf = dict((task['name'], task)
                               for task in conf["tasks"])
        self.users_conf = dict((user['username'], user)
                               for user
                               in conf["users"])
        tasks = [task['name'] for task in conf["tasks"]]
        users = [user['username'] for user in conf["users"]]

        return Contest(**args), tasks, users

    def has_changed(self, name):
        """See docstring in class Loader

        """

        conf = self.tasks_conf[name]
        path = os.path.realpath(os.path.join(self.path, name))

        # If there is no .itime file, we assume that the task has changed
        if not os.path.exists(os.path.join(path, ".itime")):
            return True

        getmtime = lambda fname: os.stat(fname).st_mtime

        itime = getmtime(os.path.join(path, ".itime"))

        # Generate a task's list of files
        files = []
        # files.append(os.path.join(path))

        # Testcases
        files.append(os.path.join(path, "in"))
        for filename in os.listdir(os.path.join(path, "in")):
            files.append(os.path.join(path, "in", filename))

        files.append(os.path.join(path, "out"))
        for filename in os.listdir(os.path.join(path, "out")):
            files.append(os.path.join(path, "out", filename))

        # Attachments
        files.append(os.path.join(path, "att"))
        if os.path.exists(os.path.join(path, "att")):
            for filename in os.listdir(os.path.join(path, "att")):
                files.append(os.path.join(path, "att", filename))
        files.append(os.path.join(path, "dist"))
        if os.path.exists(os.path.join(path, "dist")):
            for filename in os.listdir(os.path.join(path, "dist")):
                files.append(os.path.join(path, "dist", filename))

        # Score file
        files.append(os.path.join(path, "etc", "score.txt"))

        # Statement
        files.append(os.path.join(path, "task", name + "pdf"))

        # Managers
        files.append(os.path.join(path, "cms", "checker"))
        files.append(os.path.join(path, "cms", "checker.cpp"))
        files.append(os.path.join(path, "cms", "manager"))
        files.append(os.path.join(path, "cms", "manager.cpp"))
        for lang in LANGUAGES:
            files.append(os.path.join(path, "cms", "grader.%s" % lang))
        if os.path.exists(os.path.join(path, "cms")):
            files.append(os.path.join(path, "cms"))
            for other_filename in os.listdir(os.path.join(path, "cms")):
                if other_filename.endswith('.h') or \
                        other_filename.endswith('lib.pas'):
                    files.append(os.path.join(path, "cms", other_filename))

        # Check is any of the files have changed
        for fname in files:
            if os.path.exists(fname):
                if getmtime(fname) > itime:
                    return True

        # Config
        if os.path.exists(os.path.join(path, "config.cache")):
            conf_cache = json.load(
                io.open(os.path.join(path, "config.cache"),
                        "rt", encoding="utf-8"))
            if conf_cache != conf:
                return True
        else:
            return True

        if os.path.exists(os.path.join(path, ".import_error")):
            logger.warning("Last attempt to import task %s failed,"
                           " I'm not trying again." % name)
        return False

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

        load(conf, args, "hidden")

        logger.info("User parameters loaded.")

        return User(**args)

    def get_task(self, name):
        """See docstring in class Loader.

        """
        conf = self.tasks_conf[name]
        task_path = os.path.join(self.path, conf["dir"])

        getmtime = lambda fname: os.stat(fname).st_mtime
        compilation_pairs = [
                [os.path.join(task_path, "cms", "manager.cpp"),
                 os.path.join(task_path, "cms", "manager")],
                [os.path.join(task_path, "cms", "checker.cpp"),
                 os.path.join(task_path, "cms", "checker")]]
        for src,dst in compilation_pairs:
            if os.path.exists(src):
                has_src_changed = True
                if os.path.exists(dst):
                    has_src_changed = getmtime(src) > getmtime(dst)
                if has_src_changed:
                    logger.info("Auto-generation for %s." % dst)
                    os.system("g++ -O2 -Wall -static %s -lm -o %s" % (src,dst))

        logger.info("Loading parameters for task %s." % name)

        # Here we update the time of the last import
        touch(os.path.join(task_path, ".itime"))
        # If this file is not deleted, then the import failed
        touch(os.path.join(task_path, ".import_error"))

        with open(os.path.join(task_path, "config.cache"),
                    "w") as config_cache:
            json.dump(conf, config_cache)

        args = {}

        args["num"] = conf["num"]
        load(conf, args, "name")
        load(conf, args, "title")

        # assert name == args["name"]

        if args["name"] == args["title"]:
            logger.warning("Short name equals long name (title). "
                           "Please check.")

        primary_language = load(conf, None, "primary_language")
        if primary_language is None:
            primary_language = 'ja'
        paths = [os.path.join(task_path, "task",args["name"] + ".pdf")]
        for path in paths:
            if os.path.exists(path):
                digest = self.file_cacher.put_file_from_path(
                    path,
                    "Statement for task %s (lang: %s)" % (name,
                                                          primary_language))
                break
        else:
            logger.critical("Couldn't find any task statement, aborting...")
            sys.exit(1)
        args["statements"] = [Statement(primary_language, digest)]

        args["primary_statements"] = '["%s"]' % (primary_language)

        args["attachments"] = []  # FIXME Use auxiliary

        args["submission_format"] = [
            SubmissionFormatElement("%s.%%l" % name)]

        # Use the new token settings format if detected.
        load(conf, args, "token_mode")
        load(conf, args, "token_max_number")
        load(conf, args, "token_min_interval", conv=make_timedelta)
        load(conf, args, "token_gen_initial")
        load(conf, args, "token_gen_number")
        load(conf, args, "token_gen_interval", conv=make_timedelta)
        load(conf, args, "token_gen_max")

        load(conf, args, "max_submission_number")
        load(conf, args, "max_user_test_number")
        load(conf, args, "min_submission_interval", conv=make_timedelta)
        load(conf, args, "min_user_test_interval", conv=make_timedelta)

        # Attachments
        args["attachments"] = []
        if os.path.exists(os.path.join(task_path, "att")):
            for filename in os.listdir(os.path.join(task_path, "att")):
                digest = self.file_cacher.put_file_from_path(
                    os.path.join(task_path, "att", filename),
                    "Attachment %s for task %s" % (filename, name))
                args["attachments"] += [Attachment(filename, digest)]

        if os.path.exists(os.path.join(task_path, "dist")):
            zfn = tempfile.mkstemp("imojudge-loader-", ".zip")
            with zipfile.ZipFile(zfn[1], 'w', zipfile.ZIP_STORED) as zf:
                for filename in os.listdir(os.path.join(task_path, "dist")):
                    zf.write(os.path.join(task_path, "dist", filename),
                             os.path.join(name, filename))
            digest = self.file_cacher.put_file_from_path(
                zfn[1],
                "Distribution archive for task %s" % name)
            args["attachments"] += [Attachment(name + ".zip", digest)]
            os.remove(zfn[1])

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
                    digest = self.file_cacher.put_file_from_path(
                        grader_filename,
                        "Grader for task %s and language %s" % (name, lang))
                    args["managers"] += [
                        Manager("grader.%s" % lang, digest)]
                else:
                    logger.warning("Grader for language %s not found " % lang)
            compilation_param = "grader"
        else:
            compilation_param = "alone"

        # Read managers with other known file extensions
        if os.path.exists(os.path.join(task_path, "cms")):
            for other_filename in os.listdir(os.path.join(task_path, "cms")):
                if other_filename.endswith('.h') or \
                        other_filename.endswith('lib.pas'):
                    digest = self.file_cacher.put_file_from_path(
                        os.path.join(task_path, "cms", other_filename),
                        "Manager %s for task %s" % (other_filename, name))
                    args["managers"] += [
                        Manager(other_filename, digest)]

        # If there is check/checker (or equivalent), then, presuming
        # that the task type is Batch or OutputOnly, we retrieve the
        # comparator
        paths = [os.path.join(task_path, "cms", "checker")]
        for path in paths:
            if os.path.exists(path):
                digest = self.file_cacher.put_file_from_path(
                    path,
                    "Manager for task %s" % name)
                args["managers"] += [
                    Manager("checker", digest)]
                evaluation_param = "comparator"
                break
        else:
            evaluation_param = "diff"

        # enumerate test cases
        testcases = []
        for file in os.listdir(os.path.join(task_path, "in")):
            m = re.match(r'\A(.*)\.txt\Z', file)
            if m:
                testcases.append(m.group(1))
            else:
                logger.warning("file %s was not added to testcases" % file)
        testcases.sort()

        # Detect subtasks by checking score.txt
        score_filename = os.path.join(task_path, 'etc', 'score.txt')
        scoreline_re = re.compile(r'\A\s*(?:Feedback|([\w ]+)\s*\((\d+)\))'
                                  r'\s*:\s*([-\w\s*?,]+)\Z')
        try:
            with io.open(score_filename, "rt", encoding="utf-8") as score_file:
                subtasks = []
                feedback = None
                for line in score_file:
                    line = line.strip()
                    m = scoreline_re.match(line)
                    subtask_name, subscore, filelist = m.groups()
                    file_re = filelist.replace(" ","") \
                                      .replace(",","|") \
                                      .replace("*", "\w*") \
                                      .replace("?", "\w?")
                    file_re = re.compile(file_re)
                    filelist = filter(lambda f: file_re.match(f), testcases)
                    if subtask_name:
                        subtasks.append({
                            'name': subtask_name,
                            'score': int(subscore),
                            'files': filelist,
                            'reduce': "min"
                            })
                    else:
                        if feedback is None:
                            feedback = filelist
                        else:
                            logger.warning("duplicate feedback line "
                                           "in score.txt")

        # If etc/score.txt doesn't exist
        except IOError:
            logger.warning("score.txt not found")
            subtasks = [{
                'name': 'Subtask01',
                'score': 100,
                'files': testcases,
                'reduce': "min"
                }]
            feedback = None

        if feedback is None:
            feedback = testcases

        args["score_type"] = "NamedGroup"
        args["score_type_parameters"] = json.dumps(subtasks)

        args["task_type"] = conf.get('task_type', "Batch")
        # If output_only is set, then the task type is OutputOnly
        if args["task_type"] == "OutputOnly":
            args["time_limit"] = None
            args["memory_limit"] = None
            # TODO
            args["task_type_parameters"] = '["%s"]' % evaluation_param
            task.submission_format = [
                SubmissionFormatElement("output_%03d.txt" % i)
                for i in xrange(n_input)]

        # If there is cms/manager (or equivalent), then the task
        # type is Communication
        elif args["task_type"] in ["Communication", "Communication2"]:
            paths = [os.path.join(task_path, "cms", "manager")]
            for path in paths:
                if os.path.exists(path):
                    args["task_type_parameters"] = '[]'
                    digest = self.file_cacher.put_file_from_path(
                        path,
                        "Manager for task %s" % name)
                    args["managers"] += [
                        Manager("manager", digest)]
                    for lang in LANGUAGES:
                        stub_name = os.path.join(
                            task_path, "cms", "stub.%s" % lang)
                        if os.path.exists(stub_name):
                            digest = self.file_cacher.put_file_from_path(
                                stub_name,
                                "Stub for task %s and language %s" % (name,
                                                                      lang))
                            args["managers"] += [
                                Manager("stub.%s" % lang, digest)]
                        else:
                            logger.warning("Stub for language %s not "
                                           "found." % lang)
                    break
            else:
                logger.warning("manager not found")

            if args["task_type"] == "Communication2":
                task.submission_format = [
                        SubmissionFormatElement(f)
                        for f in conf["submission_format"]]

        # Otherwise, the task type is Batch
        else:
            args["task_type"] = "Batch"
            args["task_type_parameters"] = \
                '["%s", ["%s", "%s"], "%s"]' % \
                (compilation_param, infile_param, outfile_param,
                 evaluation_param)

        if args["task_type"] != "OutputOnly":
            if "time_limit" not in args:
                logger.warning("time_limit should be set")
            if "memory_limit" not in args:
                logger.warning("memory_limit should be set")

        args["testcases"] = []
        for f in testcases:
            input_digest = self.file_cacher.put_file_from_path(
                os.path.join(task_path, "in", f + ".txt"),
                "Input %s for task %s" % (f, name))
            output_digest = self.file_cacher.put_file_from_path(
                os.path.join(task_path, "out", f + ".txt"),
                "Output %s for task %s" % (f, name))
            args["testcases"] += [
                Testcase(f, f in feedback, input_digest, output_digest)]
            if args["task_type"] == "OutputOnly":
                task.attachments += [
                    Attachment("input_%s.txt" % f, input_digest)]

        dataset = Dataset(**args)
        task.active_dataset = dataset

        # Import was successful
        os.remove(os.path.join(task_path, ".import_error"))

        logger.info("Task parameters loaded.")

        return task
