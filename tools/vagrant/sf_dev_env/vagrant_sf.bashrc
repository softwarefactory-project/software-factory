# .bashrc

# Source global definitions
if [ -f /etc/bashrc ]; then
        . /etc/bashrc
fi

# Uncomment the following line if you don't like systemctl's auto-paging feature:
# export SYSTEMD_PAGER=

# User specific aliases and functions

export http_proxy="http://127.0.0.1:3128/"
export https_proxy="http://127.0.0.1:3128/"

alias rgrep='grep -r -i -n -B 2 -A 2'

export WORKON_HOME=/home/vagrant/venvs
export PROJECT_HOME=/home/vagrant/software-factory
export VIRTUALENVWRAPPER_SCRIPT=/usr/bin/virtualenvwrapper.sh
source /usr/bin/virtualenvwrapper.sh

function build_rpm() {
  o=$(pwd)
  cd /home/vagrant
  projects=""
  for p in $@; do
    projects="$projects --project $p"
  done
  sudo software-factory/sfinfo/zuul_rpm_build.py $projects --distro-info software-factory/sfinfo/sf-master.yaml --local_output /var/lib/sf/zuul-rpm-build 
  cd $o
}

function fetch_sf() {
  o=$(pwd)
  cd /home/vagrant/software-factory
  cd sfinfo && git checkout master && git fetch --all && cd -
  for repo in $(python << AAA
import yaml
repos = yaml.load(open('sfinfo/sf-master.yaml'))
for r in repos['packages']:
    suffix = r['name']
    if r['source'] == 'external':
        suffix += '-distgit'
    print suffix
    if 'distgit' in r:
        print r['distgit']
AAA); do
      git clone --quiet https://softwarefactory-project.io/r/$repo 2>/dev/null || (cd /home/vagrant/$repo && echo "Fetching $repo..." && git fetch --all && cd -);
  done
  cd $o
}
