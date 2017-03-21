#!/bin/sh -xe

# Check network
curl http://mirror.centos.org &> /dev/null || echo nameserver 8.8.8.8 | sudo tee /etc/resolv.conf

sudo packstack --allinone              \
    --nagios-install=n                 \
    --provision-demo=n                 \
    --os-manila-install=n              \
    --os-swift-install=n               \
    --os-ceilometer-install=n          \
    --os-aodh-install=n                \
    --os-gnocchi-install=n             \
    --os-panko-install=n               \
    --os-sahara-install=n              \
    --os-heat-install=n                \
    --os-magnum-install=n              \
    --os-trove-install=n               \
    --os-ironic-install=n              \
    --os-heat-cloudwatch-install=n     \
    --os-heat-cfn-install=n

sudo cp /root/keystonerc_admin .
sudo chown $USER keystonerc_admin
source ./keystonerc_admin

neutron net-create external_network  --router:external --shared
neutron subnet-create --name public_subnet --enable_dhcp=False --allocation-pool=start=192.168.200.10,end=192.168.200.200 --gateway 192.168.200.1 external_network 192.168.200.0/24


UN=user01
openstack project create $UN
openstack user create --project $UN --password userpass $UN

cat keystonerc_admin | sed -e "s/admin/$UN/g" -e "s/$OS_PASSWORD/userpass/" > keystonerc_$UN
