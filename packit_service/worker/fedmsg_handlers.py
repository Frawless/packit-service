# MIT License
#
# Copyright (c) 2018-2019 Red Hat, Inc.

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
This file defines classes for job handlers specific for Fedmsg events
"""

import logging
from typing import Type

from packit.api import PackitAPI
from packit.config import (
    JobType,
    JobTriggerType,
    JobConfig,
    get_package_config_from_repo,
)
from packit.distgit import DistGit
from packit.local_project import LocalProject
from packit.utils import get_namespace_and_repo_name

from packit_service.service.events import Event, DistGitEvent, CoprBuildEvent
from packit_service.worker.copr_db import CoprBuildDB
from packit_service.worker.handler import (
    JobHandler,
    HandlerResults,
    add_to_mapping,
    BuildStatusReporter,
    PRCheckName,
)
from packit_service.config import ServiceConfig

logger = logging.getLogger(__name__)

PROCESSED_FEDMSG_TOPICS = []


def add_topic(kls: Type["FedmsgHandler"]):
    if issubclass(kls, FedmsgHandler):
        PROCESSED_FEDMSG_TOPICS.append(kls.topic)
    return kls


def do_we_process_fedmsg_topic(topic: str) -> bool:
    """ do we process selected fedmsg topic? """
    return topic in PROCESSED_FEDMSG_TOPICS


class FedmsgHandler(JobHandler):
    """ Handlers for events from fedmsg """

    topic: str

    def __init__(self, config: ServiceConfig, job: JobConfig, event: Event):
        super().__init__(config=config, job=job, event=event)
        self._pagure_service = None

    def run(self) -> HandlerResults:
        raise NotImplementedError("This should have been implemented.")


@add_topic
@add_to_mapping
class NewDistGitCommit(FedmsgHandler):
    """ A new flag was added to a dist-git pull request """

    topic = "org.fedoraproject.prod.git.receive"
    name = JobType.sync_from_downstream
    triggers = [JobTriggerType.commit]

    def __init__(
        self, config: ServiceConfig, job: JobConfig, distgit_event: DistGitEvent
    ):
        super().__init__(config=config, job=job, event=distgit_event)
        self.distgit_event = distgit_event
        self.project = distgit_event.get_project()
        self.package_config = get_package_config_from_repo(
            self.project, distgit_event.ref
        )

    def run(self) -> HandlerResults:
        # self.project is dist-git, we need to get upstream
        dg = DistGit(self.config, self.package_config)
        self.package_config.upstream_project_url = (
            dg.get_project_url_from_distgit_spec()
        )
        if not self.package_config.upstream_project_url:
            return HandlerResults(
                success=False,
                details={
                    "msg": "URL in specfile is not set. "
                    "We don't know where the upstream project lives."
                },
            )

        n, r = get_namespace_and_repo_name(self.package_config.upstream_project_url)
        up = self.project.service.get_project(repo=r, namespace=n)
        self.local_project = LocalProject(
            git_project=up, working_dir=self.config.command_handler_work_dir
        )

        self.api = PackitAPI(self.config, self.package_config, self.local_project)
        self.api.sync_from_downstream(
            # rev is a commit
            # we use branch on purpose so we get the latest thing
            # TODO: check if rev is HEAD on {branch}, warn then?
            dist_git_branch=self.distgit_event.branch,
            upstream_branch="master",  # TODO: this should be configurable
        )
        return HandlerResults(success=True, details={})


@add_topic
@add_to_mapping
class CoprBuildStarted(FedmsgHandler):
    topic = "org.fedoraproject.prod.copr.build.start"

    def __init__(self, config: Config, job: JobConfig, event: CoprBuildEvent):
        super().__init__(config=config, job=job, event=event)

    def run(self):
        pass


@add_topic
@add_to_mapping
class CoprBuildEnded(FedmsgHandler):
    topic = "org.fedoraproject.prod.copr.build.end"

    def __init__(self, config: Config, job: JobConfig, event: CoprBuildEvent):
        super().__init__(config=config, job=job, event=event)

    def run(self):
        # get copr build from db
        db = CoprBuildDB()
        build = db.get_build(self.event.build_id)

        if not build:
            logger.warning(
                f"Build: {self.event.build_id} is not handled by packit service!"
            )
            return

        msg = "RPMs failed to be built."
        gh_state = "failure"

        if self.event.status == 1:
            msg = "RPMs were built successfully."
            gh_state = "success"

        r = BuildStatusReporter(self.event.project, build["commit_sha"])
        url = (
            "https://copr.fedorainfracloud.org/coprs/"
            f"{self.event.owner}/{self.event.project_name}/build/{self.event.build_id}/"
        )

        r.report(gh_state, msg, url=url, check_name=PRCheckName.get_build_check())
