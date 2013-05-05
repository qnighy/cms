#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# Programming contest management system
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

"""This service exports every data about the contest that CMS
knows. The process of exporting and importing again should be
idempotent.

"""

import argparse
import logging
import os
import shutil
import simplejson as json
import tempfile
import codecs

import tarfile

from cms.db import SessionGen, Contest, ask_for_contest
from cms.db.filecacher import FileCacher

from cmscontrib import sha1sum


logger = logging.getLogger(__name__)


def get_archive_info(file_name):
    """Return information about the archive name.

    file_name (string): the file name of the archive to analyze.

    return (dict): dictionary containing the following keys:
                   "basename", "extension", "write_mode"

    """
    ret = {"basename": "",
           "extension": "",
           "write_mode": "",
           }
    if not (file_name.endswith(".tar.gz")
            or file_name.endswith(".tar.bz2")
            or file_name.endswith(".tar")
            or file_name.endswith(".zip")):
        return ret

    if file_name.endswith(".tar"):
        ret["basename"] = os.path.basename(file_name[:-4])
        ret["extension"] = "tar"
        ret["write_mode"] = "w:"
    elif file_name.endswith(".tar.gz"):
        ret["basename"] = os.path.basename(file_name[:-7])
        ret["extension"] = "tar.gz"
        ret["write_mode"] = "w:gz"
    elif file_name.endswith(".tar.bz2"):
        ret["basename"] = os.path.basename(file_name[:-8])
        ret["extension"] = "tar.bz2"
        ret["write_mode"] = "w:bz2"
    elif file_name.endswith(".zip"):
        ret["basename"] = os.path.basename(file_name[:-4])
        ret["extension"] = "zip"
        ret["write_mode"] = ""

    return ret


class SubmissionExporter:
    """This service exports every data about the contest that CMS
    knows. The process of exporting and importing again should be
    idempotent.

    """
    def __init__(self, contest_id, export_target):
        self.contest_id = contest_id

        # If target is not provided, we use the contest's name.
        if export_target == "":
            with SessionGen() as session:
                contest = Contest.get_from_id(self.contest_id, session)
                self.export_target = "submissions_%s.tar.gz" % contest.name
        else:
            self.export_target = export_target

        self.file_cacher = FileCacher()

    def run(self):
        """Interface to make the class do its job."""
        return self.do_export()

    def do_export(self):
        """Run the actual export code.

        """
        logger.operation = "exporting submissions of contest %d" % self.contest_id
        logger.info("Starting export.")

        export_dir = self.export_target
        archive_info = get_archive_info(self.export_target)

        if archive_info["write_mode"] != "":
            # We are able to write to this archive.
            if os.path.exists(self.export_target):
                logger.critical("The specified file already exists, "
                                "I won't overwrite it.")
                return False
            export_dir = os.path.join(tempfile.mkdtemp(),
                                      archive_info["basename"])

        logger.info("Creating dir structure.")
        try:
            os.mkdir(export_dir)
        except OSError:
            logger.critical("The specified directory already exists, "
                            "I won't overwrite it.")
            return False

        submissions_dir = os.path.join(export_dir, "submissions")
        os.mkdir(submissions_dir)

        with SessionGen() as session:

            contest = Contest.get_from_id(self.contest_id, session)

            # Export files.
            logger.info("Exporting files.")

            for task in contest.tasks:
                os.mkdir(os.path.join(submissions_dir, task.name))
                for user in contest.users:
                    os.mkdir(os.path.join(submissions_dir, task.name, user.username))

            for submission in contest.get_submissions():
                # logger.info("%s" % ",".join(dir(submission)) )
                # logger.info("%s" % submission.files )
                submission_dir = os.path.join(submissions_dir, \
                        submission.task.name, \
                        submission.user.username, \
                        submission.timestamp.strftime("%Y%m%d%H%M%S-") + \
                        str(submission.id))
                os.mkdir(submission_dir)
                for filename, filedata in submission.files.iteritems():
                    if submission.language is not None:
                        filename = filename.replace("%l", submission.language)

                    self.file_cacher.get_file_to_path(
                        filedata.digest,
                        os.path.join(submission_dir, filename))

        # If the admin requested export to file, we do that.
        if archive_info["write_mode"] != "":
            archive = tarfile.open(self.export_target,
                                   archive_info["write_mode"])
            archive.add(export_dir, arcname=archive_info["basename"])
            archive.close()
            shutil.rmtree(export_dir)

        logger.info("Export finished.")
        logger.operation = ""

        return True


def main():
    """Parse arguments and launch process.

    """
    parser = argparse.ArgumentParser(description="Exporter of CMS submissions.")
    parser.add_argument("-c", "--contest-id", action="store", type=int,
                        help="id of contest to export")
    parser.add_argument("export_target", nargs='?', default="",
                        help="target directory or archive for export")

    args = parser.parse_args()

    if args.contest_id is None:
        args.contest_id = ask_for_contest()

    SubmissionExporter(contest_id=args.contest_id,
                    export_target=args.export_target).run()


if __name__ == "__main__":
    main()
