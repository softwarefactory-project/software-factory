Theses playbooks and script are used to prepare a pre upgrade environment duplicating
the production environment

1. Cleanup pre-upgrade project (delete instances, clean snapshot and volumes)
  ssh sf-manage-pre-upgrade
  cd software-factory/tests/pre_upgrade
  ansible-playbook cleanup_pre_upgrade_tenant.yaml --extra-vars "managesf_snapshot_id=1 elk_snapshot_id=1"

2. Create volume from snapshot for prodution instances

for each instance
  1. Stop instance
  2. Log into horizon and go to the production tenant (Project/SF-Prod), Instances, Volumes tab
  3. Create snapshot of the instance volume, use the instance name as snapshot name
  4. Start the instance
  5. Go to Volume Snapshots tab and create a new volume from snapshot (keep the instance name as volume name)
  6. In Volumes tab, select "Create transfer" in the Action column of the volume, note Transfer ID and Authorization Key to finalize the transfer in pre-upgrade tenant
  7. Select Project/sf-pre-upgrade tenant on top right, go to Instances, Volumes tab.
  8. Select Accept transfer, use previous values of Transfer ID and Authorization Key
  9. Create a snapshot of the volume with the instance name as snapshot name (this snapshot will be use to spawn all instances)

3. Lauch the deployment playbook with managesf and elk snapshot_id

  export OS_CLOUD=rcip-dev-sf-pre-upgrade
  sf_release="2.4.0"
  managesf_snapshot_id=$(openstack snapshot show -f value -c id managesf.softwarefactory-project.io)
  elk_snapshot_id=$(openstack snapshot show -f value -c id elk.softwarefactory-project.io)
  ansible-playbook spawn_pre_upgrade_instances.yaml --extra-vars "managesf_snapshot_id=$managesf_snapshot_id elk_snapshot_id=$elk_snapshot_id sf_release=$sf_release"

4. Cleaning the environment

Be carreful to clean everything in this order. There is a bug on rcip-dev, it's not possible to delete a volume created from a snapshot if the snapshot is deleted before.

  1. Delete all volumes snapshots in sf-pre-upgrade project.
  2. Delete all volumes in sf-pre-upgrade project.
  3. Delete the snapshots in SF-Prod project.
