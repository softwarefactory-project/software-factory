#!/bin/bash

set -xe

sudo yum update -y > /dev/null

# Base requirements
sudo yum install -y --nogpgcheck https://softwarefactory-project.io/repos/sf-release-${SF_RELEASE:-2.5}.rpm
sudo yum install -y git wget curl patch iproute zuul-cloner python2-glob2 zuul-swift-upload java > /dev/null

# The jenkins user. Must be able to use sudo without password
sudo useradd -m jenkins
sudo gpasswd -a jenkins wheel
echo "jenkins ALL=(ALL) NOPASSWD:ALL" | sudo tee --append /etc/sudoers.d/90-cloud-init-users
echo "Defaults   !requiretty" | sudo tee --append /etc/sudoers.d/90-cloud-init-users

# SSH key for the Jenkins user
sudo mkdir /home/jenkins/.ssh
sudo cp /opt/nodepool-scripts/authorized_keys /home/jenkins/.ssh/authorized_keys
sudo ssh-keygen -N '' -f /home/jenkins/.ssh/id_rsa
sudo chown -R jenkins /home/jenkins/.ssh
sudo chmod 700 /home/jenkins/.ssh
sudo chmod 600 /home/jenkins/.ssh/authorized_keys
sudo restorecon -R -v /home/jenkins/.ssh/authorized_keys

# Nodepool will try to connect on the fresh node using the user
# defined as username in the provider.image section conf. Usually
# it is the clouduser. So fetch it and authorize the pub key
# for that user.
cloud_user=$(egrep " name:" /etc/cloud/cloud.cfg | awk '{print $2}')
cat /opt/nodepool-scripts/authorized_keys | sudo tee -a /home/$cloud_user/.ssh/authorized_keys

# Copy slave tools
sudo cp -v /opt/nodepool-scripts/*.py /usr/local/bin/

# Install local CA
sudo cp /opt/nodepool-scripts/*.pem /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust

# sync FS, otherwise there are 0-byte sized files from the yum/pip installations
sudo sync
sudo sync

sudo cat /home/jenkins/.ssh/authorized_keys

echo "Base setup done."
