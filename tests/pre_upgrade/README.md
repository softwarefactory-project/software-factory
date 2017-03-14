Theses playbooks and script are used to prepare a pre upgrade environment duplicating
the production environment

There is 3 playbooks:
00-prepare-sf-pre-upgrade-instance.yaml: prepare the instance used to deploy the pre upgrade environment
01-setup_pre_upgrade_tenant.yaml: create security group rules
02-create-pre-upgrade-instances.yaml: spawn the environment

1. Add in your ~/.ssh/config
Host sf-pre-upgrade
    Hostname 46.231.133.58
    User fedora

2. Ensure the sf-pre-upgrade instance is up-to-date
  ansible-playbook -i inventory 00-prepare-sf-pre-upgrade-instance.yaml

3. ssh on sf-pre-upgrade
   cd software-factory/tests/pre_upgrade
   git pull # or git review -d #

4. Ensure security group rules are up-to-date
  export OS_CLOUD=rcip-dev-sf-pre-upgrade
  ansible-playbook 01-setup_pre_upgrade_tenant.yaml

5. Lauch the deployment playbook to deploy managesf and elk and inject the backup
  export OS_CLOUD=rcip-dev-sf-pre-upgrade
  sf_release="2.4.0"
  ansible-playbook 02-create-pre-upgrade-instances.yaml --extra-vars "sf_release=$sf_release"
