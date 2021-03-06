# -*- coding: utf-8 -*-

"""
Communicating with docker via rancher

NOTE: to convert the output json and read it:
https://jsonformatter.curiousconcept.com/

API examples:
https://github.com/rancher/validation-tests/tree/master/tests/v2_validation/cattlevalidationtest/core
"""

import time
from utilities.logs import get_logger
log = get_logger(__name__)


class Rancher(object):

    def __init__(self,
                 key, secret, url, project,
                 hub, hubuser, hubpass, localpath):

        ####################
        # SET URL
        self._url = url
        self._project = project
        # why? explained in http://bit.ly/2BBDJRj
        self._project_uri = "%s/projects/%s/schemas" % (url, project)
        self._hub_uri = hub
        self._hub_credentials = (hubuser, hubpass)
        self._localpath = localpath

        ####################
        self.connect(key, secret)
        # self.project_handle(project)

    def connect(self, key, secret):
        import gdapi
        self._client = gdapi.Client(
            url=self._project_uri,
            access_key=key, secret_key=secret)

    # def project_handle(self, project):
    #     return self._client.by_id_project(self._project)

    def hosts(self):
        """
        'state':'active'
        'agentIpAddress':'130.186.13.150'
        'hostname':'sdc01'
        'driver':'openstack',
        'openstackConfig':{
            'username':'pdonorio'
        'info':{
            'osInfo':{
               'dockerVersion':'Docker version 1.13.1, build 092cba3',
               'kernelVersion':'4.4.0',
               'operatingSystem':'Ubuntu 16.04 LTS'
            'diskInfo':{
               'fileSystems':{
                  '/dev/vda1':{
                     'capacity':29715

            'cpuInfo':{
               'count':8,
            'memoryInfo':{
                'memFree':20287,
                'memTotal':24111,
            "physicalHostId":"1ph3",
        """
        hosts = {}
        for data in self._client.list_host():
            host = data.get('hostname')
            if not data.get('state') == 'active':
                log.warning("Host %s not active", host)
                continue
            hosts[data.get('physicalHostId').replace('p', '')] = {
                'name': host,
                'ip': data.get('agentIpAddress'),
                'provider': data.get('driver'),
            }
        return hosts

    def obj_to_dict(self, obj):
        import json
        return json.loads(obj.__repr__().replace("'", '"'))

    def containers(self):
        """
        https://github.com/rancher/gdapi-python/blob/master/gdapi.py#L68
        'io.rancher.container.system': 'true'
        """

        system_label = 'io.rancher.container.system'

        containers = {}
        for info in self._client.list_container():

            # detect system containers
            try:
                labels = self.obj_to_dict(info.get('labels', {}))
                if labels.get(system_label) is not None:
                    # log.verbose("Skipping sycontainer: %s" % system_label)
                    continue
            except BaseException:
                pass

            # labels = info.get('data', {}).get('fields', {}).get('labels', {})
            # info.get('externalId')
            name = info.get('name')
            cid = info.get('uuid')
            if cid is None:
                labels = info.get('labels', {})
                cid = labels.get('io.rancher.container.uuid', None)
            if cid is None:
                log.warning("Container %s launching", name)
                log.pp(info)
                break
                cid = name

            containers[cid] = {
                'name': name,
                'image': info.get('imageUuid'),
                'command': info.get('command'),
                'host': info.get('hostId'),
            }

        return containers

    def list(self):

        resources = {}
        containers = self.containers()
        ckey = 'containers'

        for host_id, host_data in self.hosts().items():

            host_name = host_data.get('name')
            if ckey not in host_data:
                host_data[ckey] = {}

            for container_id, container_data in containers.items():
                if container_data.get('host') == host_id:
                    container_data.pop('host')
                    host_data['containers'][container_id] = container_data

            resources[host_name] = host_data

        return resources

    def recover_logs(self, container_name):
        import websocket as ws
        container = self.get_container_object(container_name)
        logs = container.logs(follow=False, lines=100)
        uri = logs.url + '?token=' + logs.token
        sock = ws.create_connection(uri, timeout=15)
        out = ''
        useless = "/bin/stty: 'standard input': Inappropriate ioctl for device"

        while True:
            try:
                line = sock.recv()
                if useless in line:
                    continue
            except ws.WebSocketConnectionClosedException:
                break
            else:
                out += line + '\n'

        return out

    def catalog_images(self):
        """ check if container image is there """
        catalog_url = "https://%s/v2/_catalog" % self._hub_uri
        # print(catalog_url)
        try:
            import requests
            r = requests.get(catalog_url, auth=self._hub_credentials)
            catalog = r.json()
            # print("TEST", catalog)
        except BaseException as e:
            return None
        else:
            return catalog.get('repositories', {})

    @staticmethod
    def internal_labels():
        """
        Define Rancher docker labels
        """
        # force to repull the image every time
        pull_label = "io.rancher.container.pull_image"
        # to launch containers only on selected host(s)
        host_label = "io.rancher.scheduler.affinity:host_label"
        label_key = 'host_type'
        label_value = 'qc'

        return {
            host_label: "%s=%s" % (label_key, label_value),
            pull_label: 'always',
        }

    def run(self,
            container_name, image_name,
            private=False, extras=None, wait_stopped=False
            ):

        ############
        if private:
            image_name_no_tags = image_name.split(':')[0]
            images_available = self.catalog_images()

            error = None
            if images_available is None:
                error = {'catalog': "Not reachable"}
            elif image_name_no_tags not in images_available:
                error = {'image': "Not found in our private catalog"}
            if error is not None:
                return {'error': error}

            # Add the prefix for private hub if it's there
            image_name = "%s/%s" % (self._hub_uri, image_name)

        ############
        params = {
            'name': container_name,
            'imageUuid': 'docker:' + image_name,
            'labels': self.internal_labels(),
            # entryPoint=['/bin/sh'],
            # command=['sleep', '1234567890'],
        }

        ############
        if extras is not None and isinstance(extras, dict):
            for key, value in extras.items():
                if key not in params:
                    # NOTE: this may print passwords, watch out!
                    # log.debug("Adding extra: %s = %s", key, value)
                    params[key] = value

        ############
        from gdapi import ApiError

        try:
            container = self._client.create_container(**params)
        except ApiError as e:
            log.error("Rancher fail:")
            log.pp(e.__dict__)
            return e.__dict__
        else:
            if wait_stopped:
                while True:
                    c = self.get_container_object(container_name)
                    log.debug("Container %s: %s", container_name, c.state)
                    if c.state not in ['creating', 'starting', 'running']:
                        break
                    else:
                        time.sleep(1)
            else:
                log.debug("Launched: %s", container.externalId)
            return None

    def get_container_object(self, container_name):
        for element in self._client.list_container():
            # NOTE: container name is unique in the whole cluster env
            if element.name == container_name:
                # print("found", element)
                return element

        return None

    def remove_container_by_name(self, container_name):
        obj = self.get_container_object(container_name)
        if obj is not None:
            self._client.delete(obj)
            return True
        return False

    def test(self):
        # client.list_host()
        # client.list_project()
        # client.list_service()
        pass
