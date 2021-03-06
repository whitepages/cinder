# Copyright (c) 2012 - 2014 EMC Corporation, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import time

import mock

from cinder import exception
from cinder import test
from cinder.tests.unit import fake_consistencygroup as fake_cg
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume.drivers.emc import xtremio


typ2id = {'volumes': 'vol-id',
          'snapshots': 'vol-id',
          'initiators': 'initiator-id',
          'initiator-groups': 'ig-id',
          'lun-maps': 'mapping-id',
          'consistency-groups': 'cg-id',
          'consistency-group-volumes': 'cg-vol-id',
          }

xms_data = {'xms': {1: {'version': '4.0.0'}},
            'clusters': {1: {'name': 'brick1',
                             'sys-sw-version': "4.0.0-devel_ba23ee5381eeab73",
                             'ud-ssd-space': '8146708710',
                             'ud-ssd-space-in-use': '708710',
                             'vol-size': '29884416',
                             'chap-authentication-mode': 'disabled',
                             'chap-discovery-mode': 'disabled',
                             "index": 1,
                             },
                         },
            'target-groups': {'Default': {"index": 1, },
                              },
            'iscsi-portals': {'10.205.68.5/16':
                              {"port-address":
                               "iqn.2008-05.com.xtremio:001e67939c34",
                               "ip-port": 3260,
                               "ip-addr": "10.205.68.5/16",
                               "name": "10.205.68.5/16",
                               "index": 1,
                               },
                              },
            'targets': {'X1-SC2-fc1': {'index': 1, "name": "X1-SC2-fc1",
                                       "port-address":
                                       "21:00:00:24:ff:57:b2:36",
                                       'port-state': 'up',
                                       },
                        'X1-SC2-fc2': {'index': 2, "name": "X1-SC2-fc2",
                                       "port-address":
                                       "21:00:00:24:ff:57:b2:55",
                                       'port-state': 'up',
                                       }
                        },
            'volumes': {},
            'initiator-groups': {},
            'initiators': {},
            'lun-maps': {},
            'consistency-groups': {},
            'consistency-group-volumes': {},
            }


def get_xms_obj_by_name(typ, name):
    for item in xms_data[typ].values():
        if 'name' in item and item['name'] == name:
            return item
    raise exception.NotFound()


def clean_xms_data():
    xms_data['volumes'] = {}
    xms_data['initiator-groups'] = {}
    xms_data['initiators'] = {}
    xms_data['lun-maps'] = {}
    xms_data['consistency-group-volumes'] = {}
    xms_data['consistency-groups'] = {}


def fix_data(data, object_type):
    d = {}
    for key, value in data.items():
        if 'name' in key:
            key = 'name'
        d[key] = value

    if object_type == 'lun-maps':
        d['lun'] = 1

    d[typ2id[object_type]] = ["a91e8c81c2d14ae4865187ce4f866f8a",
                              d.get('name'),
                              len(xms_data.get(object_type, [])) + 1]
    d['index'] = len(xms_data[object_type]) + 1
    return d


def get_xms_obj_key(data):
    for key in data.keys():
        if 'name' in key:
            return key


def get_obj(typ, name, idx):
    if name:
        return {"content": get_xms_obj_by_name(typ, name)}
    elif idx:
        if idx not in xms_data.get(typ, {}):
            raise exception.NotFound()
        return {"content": xms_data[typ][idx]}


def xms_request(object_type='volumes', request_typ='GET', data=None,
                name=None, idx=None, ver='v1'):
    if object_type == 'snapshots':
        object_type = 'volumes'

    try:
        res = xms_data[object_type]
    except KeyError:
        raise exception.VolumeDriverException
    if request_typ == 'GET':
        if name or idx:
            return get_obj(object_type, name, idx)
        else:
            if data and data.get('full') == 1:
                return {object_type: list(res.values())}
            else:
                return {object_type: [{"href": "/%s/%d" % (object_type,
                                                           obj['index']),
                                       "name": obj.get('name')}
                                      for obj in res.values()]}
    elif request_typ == 'POST':
        data = fix_data(data, object_type)
        name_key = get_xms_obj_key(data)
        try:
            if name_key and get_xms_obj_by_name(object_type, data[name_key]):
                raise (exception
                       .VolumeBackendAPIException
                       ('Volume by this name already exists'))
        except exception.NotFound:
            pass
        data['index'] = len(xms_data[object_type]) + 1
        xms_data[object_type][data['index']] = data
        # find the name key
        if name_key:
            data['name'] = data[name_key]
        if object_type == 'lun-maps':
            data['ig-name'] = data['ig-id']

        return {"links": [{"href": "/%s/%d" %
                          (object_type, data[typ2id[object_type]][2])}]}
    elif request_typ == 'DELETE':
        if object_type == 'consistency-group-volumes':
            data = [cgv for cgv in
                    xms_data['consistency-group-volumes'].values()
                    if cgv['vol-id'] == data['vol-id']
                    and cgv['cg-id'] == data['cg-id']][0]
        else:
            data = get_obj(object_type, name, idx)['content']
        if data:
            del xms_data[object_type][data['index']]
        else:
            raise exception.NotFound()
    elif request_typ == 'PUT':
        obj = get_obj(object_type, name, idx)['content']
        data = fix_data(data, object_type)
        del data['index']
        obj.update(data)


def xms_bad_request(object_type='volumes', request_typ='GET', data=None,
                    name=None, idx=None, ver='v1'):
    if request_typ == 'GET':
        raise exception.NotFound()
    elif request_typ == 'POST':
        raise exception.VolumeBackendAPIException('Failed to create ig')


def xms_failed_rename_snapshot_request(object_type='volumes',
                                       request_typ='GET', data=None,
                                       name=None, idx=None, ver='v1'):
    if request_typ == 'POST':
        xms_data['volumes'][27] = {}
        return {
            "links": [
                {
                    "href": "https://host/api/json/v2/types/snapshots/27",
                    "rel": "self"}]}
    elif request_typ == 'PUT':
        raise exception.VolumeBackendAPIException(data='Failed to delete')
    elif request_typ == 'DELETE':
        del xms_data['volumes'][27]


class D(dict):
    def update(self, *args, **kwargs):
        self.__dict__.update(*args, **kwargs)
        return dict.update(self, *args, **kwargs)


class CommonData(object):
    connector = {'ip': '10.0.0.2',
                 'initiator': 'iqn.1993-08.org.debian:01:222',
                 'wwpns': ["123456789012345", "123456789054321"],
                 'wwnns': ["223456789012345", "223456789054321"],
                 'host': 'fakehost',
                 }

    test_volume = {'name': 'vol1',
                   'size': 1,
                   'volume_name': 'vol1',
                   'id': '192eb39b-6c2f-420c-bae3-3cfd117f0001',
                   'provider_auth': None,
                   'project_id': 'project',
                   'display_name': 'vol1',
                   'display_description': 'test volume',
                   'volume_type_id': None,
                   'consistencygroup_id':
                   '192eb39b-6c2f-420c-bae3-3cfd117f0345',
                   }
    test_snapshot = D()
    test_snapshot.update({'name': 'snapshot1',
                          'size': 1,
                          'id': '192eb39b-6c2f-420c-bae3-3cfd117f0002',
                          'volume_name': 'vol-vol1',
                          'volume_id': '192eb39b-6c2f-420c-bae3-3cfd117f0001',
                          'project_id': 'project',
                          'consistencygroup_id':
                          '192eb39b-6c2f-420c-bae3-3cfd117f0345',
                          })
    test_snapshot.__dict__.update(test_snapshot)
    test_volume2 = {'name': 'vol2',
                    'size': 1,
                    'volume_name': 'vol2',
                    'id': '192eb39b-6c2f-420c-bae3-3cfd117f0004',
                    'provider_auth': None,
                    'project_id': 'project',
                    'display_name': 'vol2',
                    'display_description': 'test volume 2',
                    'volume_type_id': None,
                    'consistencygroup_id':
                    '192eb39b-6c2f-420c-bae3-3cfd117f0345',
                    }
    test_clone = {'name': 'clone1',
                  'size': 1,
                  'volume_name': 'vol3',
                  'id': '192eb39b-6c2f-420c-bae3-3cfd117f0003',
                  'provider_auth': None,
                  'project_id': 'project',
                  'display_name': 'clone1',
                  'display_description': 'volume created from snapshot',
                  'volume_type_id': None,
                  'consistencygroup_id':
                  '192eb39b-6c2f-420c-bae3-3cfd117f0345',
                  }
    unmanaged1 = {'id': 'unmanaged1',
                  'name': 'unmanaged1',
                  'size': 3,
                  }
    context = {'user': 'admin', }
    group = {'id': '192eb39b-6c2f-420c-bae3-3cfd117f0345',
             'name': 'cg1',
             'status': 'OK',
             }
    cgsnapshot = mock.Mock(id='192eb39b-6c2f-420c-bae3-3cfd117f9876',
                           consistencygroup_id=group['id'])

    def cgsnap_getitem(self, val):
        return self.__dict__[val]

    cgsnapshot.__getitem__ = cgsnap_getitem


@mock.patch('cinder.volume.drivers.emc.xtremio.XtremIOClient.req')
class EMCXIODriverISCSITestCase(test.TestCase):
    def setUp(self):
        super(EMCXIODriverISCSITestCase, self).setUp()
        clean_xms_data()

        config = mock.Mock()
        config.san_login = ''
        config.san_password = ''
        config.san_ip = ''
        config.xtremio_cluster_name = 'brick1'
        config.xtremio_provisioning_factor = 20.0
        config.max_over_subscription_ratio = 20.0
        config.xtremio_volumes_per_glance_cache = 100

        def safe_get(key):
            return getattr(config, key)

        config.safe_get = safe_get
        self.driver = xtremio.XtremIOISCSIDriver(configuration=config)
        self.driver.client = xtremio.XtremIOClient4(config,
                                                    config
                                                    .xtremio_cluster_name)
        self.data = CommonData()

    def test_check_for_setup_error(self, req):
        req.side_effect = xms_request
        clusters = xms_data['clusters']
        del xms_data['clusters']
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)
        xms_data['clusters'] = clusters
        self.driver.check_for_setup_error()

    def test_create_extend_delete_volume(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.extend_volume(self.data.test_volume, 5)
        self.driver.delete_volume(self.data.test_volume)

    def test_create_delete_snapshot(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot)
        self.assertEqual(self.data.test_snapshot['id'],
                         xms_data['volumes'][2]['name'])
        self.driver.delete_snapshot(self.data.test_snapshot)
        self.driver.delete_volume(self.data.test_volume)

    def test_failed_rename_snapshot(self, req):
        req.side_effect = xms_failed_rename_snapshot_request
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          self.data.test_snapshot)
        self.assertEqual(0, len(xms_data['volumes']))

    def test_volume_from_snapshot(self, req):
        req.side_effect = xms_request
        xms_data['volumes'] = {}
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot)
        self.driver.create_volume_from_snapshot(self.data.test_volume2,
                                                self.data.test_snapshot)
        self.driver.delete_volume(self.data.test_volume2)
        self.driver.delete_volume(self.data.test_snapshot)
        self.driver.delete_volume(self.data.test_volume)

    def test_clone_volume(self, req):
        req.side_effect = xms_request
        self.driver.db = mock.Mock()
        (self.driver.db.
         image_volume_cache_get_by_volume_id.return_value) = mock.MagicMock()
        self.driver.create_volume(self.data.test_volume)
        vol = xms_data['volumes'][1]
        vol['num-of-dest-snaps'] = 200
        self.assertRaises(exception.CinderException,
                          self.driver.create_cloned_volume,
                          self.data.test_clone,
                          self.data.test_volume)

        vol['num-of-dest-snaps'] = 50
        self.driver.create_cloned_volume(self.data.test_clone,
                                         self.data.test_volume)
        self.driver.delete_volume(self.data.test_clone)
        self.driver.delete_volume(self.data.test_volume)

        mock.patch.object(self.driver.client,
                          'create_snapshot',
                          mock.Mock(side_effect=
                                    exception.XtremIOSnapshotsLimitExceeded()))
        self.assertRaises(exception.CinderException,
                          self.driver.create_cloned_volume,
                          self.data.test_clone,
                          self.data.test_volume)

        response = mock.MagicMock()
        response.status_code = 400
        response.json.return_value = {
            "message": "too_many_snapshots_per_vol",
            "error_code": 400
        }
        self.assertRaises(exception.XtremIOSnapshotsLimitExceeded,
                          self.driver.client.handle_errors,
                          response, '', '')
        response.json.return_value = {
            "message": "too_many_objs",
            "error_code": 400
        }
        self.assertRaises(exception.XtremIOSnapshotsLimitExceeded,
                          self.driver.client.handle_errors,
                          response, '', '')

    def test_duplicate_volume(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, self.data.test_volume)
        self.driver.delete_volume(self.data.test_volume)

    def test_no_portals_configured(self, req):
        req.side_effect = xms_request
        portals = xms_data['iscsi-portals'].copy()
        xms_data['iscsi-portals'].clear()
        lunmap = {'lun': 4}
        self.assertRaises(exception.VolumeDriverException,
                          self.driver._get_iscsi_properties, lunmap)
        xms_data['iscsi-portals'] = portals

    def test_initialize_terminate_connection(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        map_data = self.driver.initialize_connection(self.data.test_volume,
                                                     self.data.connector)
        self.assertEqual(1, map_data['data']['target_lun'])
        i1 = xms_data['initiators'][1]
        i1['ig-id'] = ['', i1['ig-id'], 1]
        i1['chap-authentication-initiator-password'] = 'chap_password1'
        i1['chap-discovery-initiator-password'] = 'chap_password2'
        map_data = self.driver.initialize_connection(self.data.test_volume2,
                                                     self.data.connector)
        self.driver.terminate_connection(self.data.test_volume,
                                         self.data.connector)

    def test_initialize_chap_connection(self, req):
        req.side_effect = xms_request
        clean_xms_data()
        self.driver.create_volume(self.data.test_volume)
        map_data = self.driver.initialize_connection(self.data.test_volume,
                                                     self.data.connector)
        self.assertIsNone(map_data['data'].get('access_mode'))
        c1 = xms_data['clusters'][1]
        c1['chap-authentication-mode'] = 'initiator'
        c1['chap-discovery-mode'] = 'initiator'
        i1 = xms_data['initiators'][1]
        i1['ig-id'] = ['', i1['ig-id'], 1]
        i1['chap-authentication-initiator-password'] = 'chap_password1'
        i1['chap-discovery-initiator-password'] = 'chap_password2'
        map_data = self.driver.initialize_connection(self.data.test_volume2,
                                                     self.data.connector)
        self.assertEqual('chap_password1', map_data['data']['auth_password'])
        self.assertEqual('chap_password2',
                         map_data['data']['discovery_auth_password'])
        i1['chap-authentication-initiator-password'] = None
        i1['chap-discovery-initiator-password'] = None
        map_data = self.driver.initialize_connection(self.data.test_volume2,
                                                     self.data.connector)
        data = {}
        self.driver._add_auth(data, True, True)
        self.assertIn('initiator-discovery-user-name', data,
                      'Missing discovery user in data')
        self.assertIn('initiator-discovery-password', data,
                      'Missing discovery password in data')

    def test_initialize_connection_bad_ig(self, req):
        req.side_effect = xms_bad_request
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          self.data.test_volume,
                          self.data.connector)
        self.driver.delete_volume(self.data.test_volume)

    def test_get_stats(self, req):
        req.side_effect = xms_request
        stats = self.driver.get_volume_stats(True)
        self.assertEqual(self.driver.backend_name,
                         stats['volume_backend_name'])

    def test_manage_unmanage(self, req):
        req.side_effect = xms_request
        xms_data['volumes'] = {1: {'name': 'unmanaged1',
                                   'index': 1,
                                   'vol-size': '3',
                                   },
                               }
        ref_vol = {"source-name": "unmanaged1"}
        invalid_ref = {"source-name": "invalid"}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          self.data.test_volume, invalid_ref)
        self.driver.manage_existing_get_size(self.data.test_volume, ref_vol)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          self.data.test_volume, invalid_ref)
        self.driver.manage_existing(self.data.test_volume, ref_vol)
        self.assertRaises(exception.VolumeNotFound, self.driver.unmanage,
                          self.data.test_volume2)
        self.driver.unmanage(self.data.test_volume)

    @mock.patch('cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_cg_operations(self, get_all_for_cgsnapshot, req):
        req.side_effect = xms_request
        d = self.data
        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        get_all_for_cgsnapshot.return_value = [snapshot_obj]

        self.driver.create_consistencygroup(d.context, d.group)
        self.assertEqual(1, len(xms_data['consistency-groups']))
        self.driver.update_consistencygroup(d.context, d.group,
                                            add_volumes=[d.test_volume,
                                                         d.test_volume2])
        self.assertEqual(2, len(xms_data['consistency-group-volumes']))
        self.driver.update_consistencygroup(d.context, d.group,
                                            remove_volumes=[d.test_volume2])
        self.assertEqual(1, len(xms_data['consistency-group-volumes']))
        self.driver.db = mock.Mock()
        (self.driver.db.
         volume_get_all_by_group.return_value) = [mock.MagicMock()]
        self.driver.create_cgsnapshot(d.context, d.cgsnapshot, [])
        snapset_name = self.driver._get_cgsnap_name(d.cgsnapshot)
        self.assertEqual(snapset_name,
                         '192eb39b6c2f420cbae33cfd117f0345192eb39b6c2f420cbae'
                         '33cfd117f9876')
        snapset1 = {'ancestor-vol-id': ['', d.test_volume['id'], 2],
                    'consistencygroup_id': d.group['id'],
                    'name': snapset_name,
                    'index': 1}
        xms_data['snapshot-sets'] = {snapset_name: snapset1, 1: snapset1}
        self.driver.delete_cgsnapshot(d.context, d.cgsnapshot, [])
        self.driver.delete_consistencygroup(d.context, d.group, [])
        xms_data['snapshot-sets'] = {}

    @mock.patch('cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_cg_from_src(self, get_all_for_cgsnapshot, req):
        req.side_effect = xms_request
        d = self.data

        self.assertRaises(exception.InvalidInput,
                          self.driver.create_consistencygroup_from_src,
                          d.context, d.group, [], None, None, None, None)

        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        snapshot_obj.volume_id = d.test_volume['id']
        get_all_for_cgsnapshot.return_value = [snapshot_obj]

        self.driver.create_consistencygroup(d.context, d.group)
        self.driver.create_volume(d.test_volume)
        self.driver.create_cgsnapshot(d.context, d.cgsnapshot, [])
        xms_data['volumes'][2]['ancestor-vol-id'] = (xms_data['volumes'][1]
                                                     ['vol-id'])
        snapset_name = self.driver._get_cgsnap_name(d.cgsnapshot)

        snapset1 = {'vol-list': [xms_data['volumes'][2]['vol-id']],
                    'name': snapset_name,
                    'index': 1}
        xms_data['snapshot-sets'] = {snapset_name: snapset1, 1: snapset1}
        cg_obj = fake_cg.fake_consistencyobject_obj(d.context)
        new_vol1 = fake_volume.fake_volume_obj(d.context)
        snapshot1 = (fake_snapshot
                     .fake_snapshot_obj
                     (d.context, volume_id=d.test_volume['id']))
        self.driver.create_consistencygroup_from_src(d.context, cg_obj,
                                                     [new_vol1],
                                                     d.cgsnapshot, [snapshot1])

        new_cg_obj = fake_cg.fake_consistencyobject_obj(d.context, id=5)
        snapset2_name = new_cg_obj.id
        new_vol1.id = '192eb39b-6c2f-420c-bae3-3cfd117f0001'
        new_vol2 = fake_volume.fake_volume_obj(d.context)
        snapset2 = {'vol-list': [xms_data['volumes'][2]['vol-id']],
                    'name': snapset2_name,
                    'index': 1}
        xms_data['snapshot-sets'].update({5: snapset2,
                                          snapset2_name: snapset2})
        self.driver.create_consistencygroup_from_src(d.context, new_cg_obj,
                                                     [new_vol2],
                                                     None, None,
                                                     cg_obj, [new_vol1])


@mock.patch('requests.request')
class EMCXIODriverTestCase(test.TestCase):
    def setUp(self):
        super(EMCXIODriverTestCase, self).setUp()

        configuration = mock.Mock()
        configuration.san_login = ''
        configuration.san_password = ''
        configuration.san_ip = ''
        configuration.xtremio_cluster_name = ''
        configuration.driver_ssl_cert_verify = True
        configuration.driver_ssl_cert_path = '/test/path/root_ca.crt'

        def safe_get(key):
            return getattr(configuration, key)

        configuration.safe_get = safe_get
        self.driver = xtremio.XtremIOISCSIDriver(configuration=configuration)

        self.data = CommonData()

    @mock.patch.object(time, 'sleep', mock.Mock(return_value=0))
    def test_retry_request(self, req):
        busy_response = mock.MagicMock()
        busy_response.status_code = 400
        busy_response.json.return_value = {
            "message": "system_is_busy",
            "error_code": 400
        }
        good_response = mock.MagicMock()
        good_response.status_code = 200

        EMCXIODriverTestCase.req_count = 0

        def busy_request(*args, **kwargs):
            if EMCXIODriverTestCase.req_count < 1:
                EMCXIODriverTestCase.req_count += 1
                return busy_response
            return good_response

        req.side_effect = busy_request
        self.driver.create_volume(self.data.test_volume)

    def test_verify_cert(self, req):
        good_response = mock.MagicMock()
        good_response.status_code = 200

        def request_verify_cert(*args, **kwargs):
            self.assertEqual(kwargs['verify'], '/test/path/root_ca.crt')
            return good_response

        req.side_effect = request_verify_cert
        self.driver.client.req('volumes')


@mock.patch('cinder.volume.drivers.emc.xtremio.XtremIOClient.req')
class EMCXIODriverFibreChannelTestCase(test.TestCase):
    def setUp(self):
        super(EMCXIODriverFibreChannelTestCase, self).setUp()
        clean_xms_data()

        self.config = mock.Mock(san_login='',
                                san_password='',
                                san_ip='',
                                xtremio_cluster_name='',
                                xtremio_provisioning_factor=20.0)
        self.driver = xtremio.XtremIOFibreChannelDriver(
            configuration=self.config)
        self.data = CommonData()

    def test_initialize_terminate_connection(self, req):
        req.side_effect = xms_request
        self.driver.client = xtremio.XtremIOClient4(
            self.config, self.config.xtremio_cluster_name)

        self.driver.create_volume(self.data.test_volume)
        map_data = self.driver.initialize_connection(self.data.test_volume,
                                                     self.data.connector)
        self.assertEqual(1, map_data['data']['target_lun'])
        self.driver.terminate_connection(self.data.test_volume,
                                         self.data.connector)
        self.driver.delete_volume(self.data.test_volume)

    def test_initialize_existing_ig_terminate_connection(self, req):
        req.side_effect = xms_request
        self.driver.client = xtremio.XtremIOClient4(
            self.config, self.config.xtremio_cluster_name)

        self.driver.create_volume(self.data.test_volume)

        pre_existing = 'pre_existing_host'
        self.driver._create_ig(pre_existing)
        wwpns = self.driver._get_initiator_name(self.data.connector)
        for wwpn in wwpns:
            data = {'initiator-name': wwpn, 'ig-id': pre_existing,
                    'port-address': wwpn}
            self.driver.client.req('initiators', 'POST', data)

        def get_fake_initiator(wwpn):
            return {'port-address': wwpn, 'ig-id': ['', pre_existing, 1]}
        with mock.patch.object(self.driver.client, 'get_initiator',
                               side_effect=get_fake_initiator):
            map_data = self.driver.initialize_connection(self.data.test_volume,
                                                         self.data.connector)
        self.assertEqual(1, map_data['data']['target_lun'])
        self.assertEqual(1, len(xms_data['initiator-groups']))
        self.driver.terminate_connection(self.data.test_volume,
                                         self.data.connector)
        self.driver.delete_volume(self.data.test_volume)

    def test_race_on_terminate_connection(self, req):
        """Test for race conditions on num_of_mapped_volumes.

        This test confirms that num_of_mapped_volumes won't break even if we
        receive a NotFound exception when retrieving info on a specific
        mapping, as that specific mapping could have been deleted between
        the request to get the list of exiting mappings and the request to get
        the info on one of them.
        """
        req.side_effect = xms_request
        self.driver.client = xtremio.XtremIOClient3(
            self.config, self.config.xtremio_cluster_name)
        # We'll wrap num_of_mapped_volumes, we'll store here original method
        original_method = self.driver.client.num_of_mapped_volumes

        def fake_num_of_mapped_volumes(*args, **kwargs):
            # Add a nonexistent mapping
            mappings = [{'href': 'volumes/1'}, {'href': 'volumes/12'}]

            # Side effects will be: 1st call returns the list, then we return
            # data for existing mappings, and on the nonexistent one we added
            # we return NotFound
            side_effect = [{'lun-maps': mappings},
                           {'content': xms_data['lun-maps'][1]},
                           exception.NotFound]

            with mock.patch.object(self.driver.client, 'req',
                                   side_effect=side_effect):
                return original_method(*args, **kwargs)

        self.driver.create_volume(self.data.test_volume)
        map_data = self.driver.initialize_connection(self.data.test_volume,
                                                     self.data.connector)
        self.assertEqual(1, map_data['data']['target_lun'])
        with mock.patch.object(self.driver.client, 'num_of_mapped_volumes',
                               side_effect=fake_num_of_mapped_volumes):
            self.driver.terminate_connection(self.data.test_volume,
                                             self.data.connector)
        self.driver.delete_volume(self.data.test_volume)
