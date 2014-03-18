#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# Programming contest management system
# Copyright © 2010-2012 Giovanni Mascellani <mascellani@poisson.phc.unipi.it>
# Copyright © 2010-2012 Stefano Maggiolo <s.maggiolo@gmail.com>
# Copyright © 2010-2012 Matteo Boscariol <boscarim@hotmail.com>
# Copyright © 2012-2013 Luca Wehrstedt <luca.wehrstedt@gmail.com>
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

import logging
import os
import tempfile

from cms import LANGUAGES, LANGUAGE_TO_SOURCE_EXT_MAP, config
from cms.grading.Sandbox import Sandbox, wait_without_std
from cms.grading import get_compilation_commands, compilation_step, \
    human_evaluation_message, is_evaluation_passed, \
    extract_outcome_and_text, evaluation_step_before_run, \
    evaluation_step_after_run
from cms.grading.TaskType import TaskType, \
    create_sandbox, delete_sandbox
from cms.db import Executable
from cms.io.GeventUtils import rmtree


logger = logging.getLogger(__name__)


# Dummy function to mark translatable string.
def N_(message):
    return message


class Communication2(TaskType):
    """Task type class for tasks that requires:

    - a *manager* that reads the input file, work out the perfect
      solution on its own, and communicate the input (maybe with some
      modifications) on its standard output; it then reads the
      response of the user's solution from the standard input and
      write the outcome;

    - a *stub* that compiles with the user's source, reads from
      standard input what the manager says, and write back the user's
      solution to stdout.

    """
    ALLOW_PARTIAL_SUBMISSION = False

    name = "Communication2"

    def get_compilation_commands(self, submission_format):
        """See TaskType.get_compilation_commands."""
        res = dict()
        for language in LANGUAGES:
            source_ext = LANGUAGE_TO_SOURCE_EXT_MAP[language]
            source_filenames = []
            source_filenames.append("stub%s" % source_ext)
            for filename in submission_format:
                source_filename = filename.replace(".%l", source_ext)
                source_filenames.append(source_filename)
            executable_filename = "user_program"
            commands = get_compilation_commands(language,
                                                source_filenames,
                                                executable_filename)
            res[language] = commands
        return res

    def get_user_managers(self, submission_format):
        """See TaskType.get_user_managers."""
        return ["stub.%l"]

    def get_auto_managers(self):
        """See TaskType.get_auto_managers."""
        return ["manager"]

    def compile(self, job, file_cacher):
        """See TaskType.compile."""
        # Detect the submission's language. The checks about the
        # formal correctedness of the submission are done in CWS,
        # before accepting it.
        language = job.language
        source_ext = LANGUAGE_TO_SOURCE_EXT_MAP[language]

        # TODO: here we are sure that submission.files are the same as
        # task.submission_format. The following check shouldn't be
        # here, but in the definition of the task, since this actually
        # checks that task's task type and submission format agree.
        if len(job.files) != 2:
            job.success = True
            job.compilation_success = False
            job.text = [N_("Invalid files in submission")]
            logger.error("Submission contains %d files, expecting 1" %
                         len(job.files), extra={"operation": job.info})
            return True

        # Create the sandbox
        sandbox = create_sandbox(file_cacher)
        job.sandboxes.append(sandbox.path)

        # Prepare the source files in the sandbox
        files_to_get = {}
        source_filenames = []
        # Stub.
        source_filenames.append("stub%s" % source_ext)
        files_to_get[source_filenames[-1]] = \
            job.managers["stub%s" % source_ext].digest
        # User's submission.
        for filename, file_ in job.files.iteritems():
            source_filename = filename.replace(".%l", source_ext)
            source_filenames.append(source_filename)
            files_to_get[source_filename] = file_.digest

        # Also copy all *.h and *lib.pas graders
        for filename in job.managers.iterkeys():
            if filename.endswith('.h') or \
                    filename.endswith('lib.pas'):
                files_to_get[filename] = \
                    job.managers[filename].digest

        for filename, digest in files_to_get.iteritems():
            sandbox.create_file_from_storage(filename, digest)

        # Prepare the compilation command
        executable_filename = "user_program"
        commands = get_compilation_commands(language,
                                            source_filenames,
                                            executable_filename)

        # Run the compilation
        operation_success, compilation_success, text, plus = \
            compilation_step(sandbox, commands)

        # Retrieve the compiled executables
        job.success = operation_success
        job.compilation_success = compilation_success
        job.plus = plus
        job.text = text
        if operation_success and compilation_success:
            digest = sandbox.get_file_to_storage(
                executable_filename,
                "Executable %s for %s" %
                (executable_filename, job.info))
            job.executables[executable_filename] = \
                Executable(executable_filename, digest)

        # Cleanup
        delete_sandbox(sandbox)

    def evaluate(self, job, file_cacher):
        """See TaskType.evaluate."""
        # Create sandboxes and FIFOs
        sandbox_mgr = create_sandbox(file_cacher)
        sandbox_user1 = create_sandbox(file_cacher)
        sandbox_user2 = create_sandbox(file_cacher)
        fifo1_dir = tempfile.mkdtemp(dir=config.temp_dir)
        fifo2_dir = tempfile.mkdtemp(dir=config.temp_dir)
        fifo1_in = os.path.join(fifo1_dir, "in1")
        fifo1_out = os.path.join(fifo1_dir, "out1")
        fifo2_in = os.path.join(fifo2_dir, "in2")
        fifo2_out = os.path.join(fifo2_dir, "out2")
        os.mkfifo(fifo1_in)
        os.mkfifo(fifo1_out)
        os.mkfifo(fifo2_in)
        os.mkfifo(fifo2_out)
        os.chmod(fifo1_dir, 0o755)
        os.chmod(fifo1_in, 0o666)
        os.chmod(fifo1_out, 0o666)
        os.chmod(fifo2_dir, 0o755)
        os.chmod(fifo2_in, 0o666)
        os.chmod(fifo2_out, 0o666)

        # First step: we start the manager.
        manager_filename = "manager"
        manager_command = ["./%s" % manager_filename, fifo1_in, fifo1_out, fifo2_in, fifo2_out]
        manager_executables_to_get = {
            manager_filename:
            job.managers[manager_filename].digest
            }
        manager_files_to_get = {
            "input.txt": job.input
            }
        manager_allow_dirs = [fifo1_dir, fifo2_dir]
        for filename, digest in manager_executables_to_get.iteritems():
            sandbox_mgr.create_file_from_storage(
                filename, digest, executable=True)
        for filename, digest in manager_files_to_get.iteritems():
            sandbox_mgr.create_file_from_storage(filename, digest)
        manager = evaluation_step_before_run(
            sandbox_mgr,
            manager_command,
            job.time_limit,
            0,
            allow_dirs=manager_allow_dirs,
            stdin_redirect="input.txt")

        # Second step: we start the user submission compiled with the
        # stub.
        executable_filename = job.executables.keys()[0]
        executables_to_get = {
            executable_filename:
            job.executables[executable_filename].digest
            }

        command1 = ["./%s" % executable_filename, "0", fifo1_out, fifo1_in]
        user_allow_dirs = [fifo1_dir]
        for filename, digest in executables_to_get.iteritems():
            sandbox_user1.create_file_from_storage(
                filename, digest, executable=True)
        process1 = evaluation_step_before_run(
            sandbox_user1,
            command1,
            job.time_limit,
            job.memory_limit,
            allow_dirs=user_allow_dirs)

        command2 = ["./%s" % executable_filename, "1", fifo2_out, fifo2_in]
        user_allow_dirs = [fifo2_dir]
        for filename, digest in executables_to_get.iteritems():
            sandbox_user2.create_file_from_storage(
                filename, digest, executable=True)
        process2 = evaluation_step_before_run(
            sandbox_user2,
            command2,
            job.time_limit,
            job.memory_limit,
            allow_dirs=user_allow_dirs)

        # Consume output.
        wait_without_std([process1, process2, manager])
        # TODO: check exit codes with translate_box_exitcode.

        success_user1, plus_user1 = \
            evaluation_step_after_run(sandbox_user1)
        success_user2, plus_user2 = \
            evaluation_step_after_run(sandbox_user2)
        success_mgr, plus_mgr = \
            evaluation_step_after_run(sandbox_mgr)

        # merge two results
        success_user = success_user1 and success_user2
        plus_user = {
            "execution_time": 0.0,
            "execution_wall_clock_time": 0.0,
            "execution_memory": 0,
            "exit_status": Sandbox.EXIT_OK,
            }
        for plus in [plus_user1, plus_user2]:
            plus_user["execution_time"] += plus["execution_time"]
            plus_user["execution_wall_clock_time"] += \
                    plus["execution_wall_clock_time"]
            plus_user["execution_memory"] += plus["execution_memory"]
        for plus in [plus_user1, plus_user2]:
            if plus["exit_status"] == Sandbox.EXIT_SIGNAL:
                plus_user["signal"] = plus["signal"]
            elif plus["exit_status"] == Sandbox.EXIT_SYSCALL:
                plus_user["syscall"] = plus["syscall"]
            elif plus["exit_status"] == Sandbox.EXIT_FILE_ACCESS:
                plus_user["filename"] = plus["filename"]
            if plus["exit_status"] != Sandbox.EXIT_OK:
                plus_user["exit_status"] = plus["exit_status"]
                break

        job.sandboxes = [sandbox_user1.path,
                         sandbox_user2.path,
                         sandbox_mgr.path]
        job.plus = plus_user

        # If at least one evaluation had problems, we report the
        # problems.
        if not success_user or not success_mgr:
            success, outcome, text = False, None, None
        # If the user sandbox detected some problem (timeout, ...),
        # the outcome is 0.0 and the text describes that problem.
        elif not is_evaluation_passed(plus_user):
            success = True
            outcome, text = 0.0, human_evaluation_message(plus_user)
        # Otherwise, we use the manager to obtain the outcome.
        else:
            success = True
            outcome, text = extract_outcome_and_text(sandbox_mgr)

        # If asked so, save the output file, provided that it exists
        if job.get_output:
            if sandbox_mgr.file_exists("output.txt"):
                job.user_output = sandbox_mgr.get_file_to_storage(
                    "output.txt",
                    "Output file in job %s" % job.info)
            else:
                job.user_output = None

        # Whatever happened, we conclude.
        job.success = success
        job.outcome = str(outcome) if outcome is not None else None
        job.text = text

        delete_sandbox(sandbox_mgr)
        delete_sandbox(sandbox_user1)
        delete_sandbox(sandbox_user2)
        rmtree(fifo1_dir)
        rmtree(fifo2_dir)
