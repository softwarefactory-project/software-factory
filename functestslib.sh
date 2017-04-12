#!/bin/bash

[ -z "${DEBUG}" ] || set -x

export SF_HOST=${SF_HOST:-sftests.com}
export SKIP_CLEAN_ROLES="y"

MANAGESF_URL=https://${SF_HOST}
JENKINS_URL="https://${SF_HOST}/jenkinslogs/${JENKINS_IP}:8081/"

ARTIFACTS_DIR="/var/lib/sf/artifacts"
# This environment variable is set ZUUL in the jenkins job workspace
# The artifacts directory is then at the root of workspace
[ -n "$SWIFT_artifacts_URL" ] && ARTIFACTS_DIR="$(pwd)/../artifacts"

# Make sure .local/bin is in PATH for --user install
echo ${PATH} | grep -q "\.local/bin" || {
    echo "Adding ${HOME}/.local/bin to PATH"
    export PATH="${PATH}:${HOME}/.local/bin"
}

function prepare_artifacts {
    [ -d ${ARTIFACTS_DIR} ] && sudo rm -Rf ${ARTIFACTS_DIR}
    sudo mkdir -p ${ARTIFACTS_DIR}
    USER=$(whoami)
    sudo chown -R $USER:$USER ${ARTIFACTS_DIR}
    sudo chmod -R 755 ${ARTIFACTS_DIR}
    set +x
    if [ -n "${SWIFT_artifacts_URL}" ]; then
        echo "Logs will be available here: $SWIFT_artifacts_URL"
    else
        echo "Logs will be available here: ${ARTIFACTS_DIR}"
    fi
    set -x
}

function lxc_stop {
    (cd deploy/lxc; sudo ./deploy.py --workspace ${SF_WORKSPACE} stop)
    checkpoint "lxc-stop"
}

function lxc_poweroff {
    ssh ${SF_HOST} sync
    (cd deploy/lxc; sudo ./deploy.py --workspace ${SF_WORKSPACE} poweroff)
    checkpoint "lxc-poweroff"
}

function lxc_init {
    ver=${1:-${SF_VER}}
    (cd deploy/lxc; sudo ./deploy.py init --workspace ${SF_WORKSPACE} --arch ${REFARCH_FILE} --version ${ver}) || fail "LXC start FAILED"
    checkpoint "lxc-start"
}

function lxc_start {
    (cd deploy/lxc; sudo ./deploy.py start --workspace ${SF_WORKSPACE} --arch ${REFARCH_FILE}) || fail "LXC start FAILED"
    checkpoint "lxc-start"
}

function heat_stop {
    STOP_RETRY=3
    while [ $STOP_RETRY -gt 0 ]; do
        heat stack-delete -y sf_stack &> /dev/null
        RETRY=40
        while [ $RETRY -gt 0 ]; do
            heat stack-show sf_stack &> /dev/null || break
            sleep 5
            let RETRY--
        done
        [ $RETRY -gt 0 ] && break
        let STOP_RETRY--
    done
    [ $STOP_RETRY -eq 0 ] && fail "Heat stack-delete failed..."
    checkpoint "heat-stop"
}

function clean_nodepool_tenant {
    echo "[+] Cleaning nodepool tenant"
    openstack server delete managesf.sftests.com &> /dev/null
    for srv in $(openstack  server list -f json | grep base_centos | awk '{ print $2 }' | tr ',' ' ' | sed 's/"//g'); do
        openstack server delete $srv
    done
    for image in $(nova image-list | grep 'template\|base_centos-default' | awk '{ print $2 }'); do
        nova image-delete $image
    done
    checkpoint "clean nodepool tenant"
}

function run_health_base {
    echo "[+] Starting the health base check"
    echo "$(date) Running /etc/ansible/health-check/zuul.yaml" | tee -a ${ARTIFACTS_DIR}/integration_tests.txt
    ssh ${SF_HOST} ansible-playbook /etc/ansible/health-check/zuul.yaml >> ${ARTIFACTS_DIR}/integration_tests.txt \
        && echo "Zuul integration test SUCCESS"                        \
        || fail "Zuul integration test failed" ${ARTIFACTS_DIR}/integration_tests.txt
    echo "$(date) Running /etc/ansible/health-check/gerritbot.yaml" | tee -a ${ARTIFACTS_DIR}/integration_tests.txt
    ssh ${SF_HOST} ansible-playbook /etc/ansible/health-check/gerritbot.yaml >> ${ARTIFACTS_DIR}/integration_tests.txt \
        && echo "Gerritbot integration test SUCCESS"                        \
        || fail "Gerritbot integration test failed" ${ARTIFACTS_DIR}/integration_tests.txt
    checkpoint "run_health_base"
}

function run_health_openstack {
    echo "[+] Starting the health openstack check"
    export OS_AUTH_URL=${OS_AUTH_URL:-"http://192.168.42.1:5000/v2.0"}
    EXTRA_VARS="node=base_centos os_slave_network=${HEAT_SLAVE_NETWORK}"
    EXTRA_VARS+=" os_auth_url=${OS_AUTH_URL} os_username=${OS_USERNAME} os_password=${OS_PASSWORD} os_tenant_name=${OS_TENANT_NAME}"
    EXTRA_VARS+=" os_tempurl_key=${RANDOM}${RANDOM}${RANDOM}"
    echo "$(date) Running /etc/ansible/health-check/nodepool.yaml" | tee -a ${ARTIFACTS_DIR}/integration_tests.txt
    # Debug playbook
    ssh ${SF_HOST} << EOF
echo ansible-playbook "--extra-vars='${EXTRA_VARS}'" /etc/ansible/health-check/nodepool.yaml >> /root/debug_playbooks
EOF
    ssh ${SF_HOST} ansible-playbook "--extra-vars='${EXTRA_VARS}'" /etc/ansible/health-check/nodepool.yaml >> ${ARTIFACTS_DIR}/integration_tests.txt \
        && echo "Nodepool integration test SUCCESS"    \
        || fail "Nodepool integration test failed" ${ARTIFACTS_DIR}/integration_tests.txt
    echo "$(date) Running /etc/ansible/health-check/swiftlogs.yaml" | tee -a ${ARTIFACTS_DIR}/integration_tests.txt
    # Debug playbook
    ssh ${SF_HOST} << EOF
echo ansible-playbook "--extra-vars='${EXTRA_VARS}'" /etc/ansible/health-check/swiftlogs.yaml >> /root/debug_playbooks
EOF
    ssh ${SF_HOST} ansible-playbook "--extra-vars='${EXTRA_VARS}'" /etc/ansible/health-check/swiftlogs.yaml >> ${ARTIFCATS_DIR}/integration_tests.txt \
        && { echo "Swiftlogs integration test SUCCESS"; EXTRA_VARS+=" test_log_export=yes"; }    \
        || echo "Swiftlogs integration test failed (non-voting)"
    echo "$(date) Running /etc/ansible/health-check/zuul.yaml" | tee -a ${ARTIFACTS_DIR}/integration_tests.txt
    # Debug playbook
    ssh ${SF_HOST} << EOF
echo ansible-playbook "--extra-vars='${EXTRA_VARS}'" /etc/ansible/health-check/zuul.yaml >> /root/debug_playbooks
EOF
    ssh ${SF_HOST} ansible-playbook "--extra-vars='${EXTRA_VARS}'" /etc/ansible/health-check/zuul.yaml >> ${ARTIFACTS_DIR}/integration_tests.txt \
        && echo "Zuul integration test SUCCESS"                        \
        || fail "Zuul integration test failed" ${ARTIFACTS_DIR}/integration_tests.txt
    checkpoint "run_it_openstack"
}

function heat_init {
    GLANCE_ID=$(glance image-list | grep "sf-${SF_VER}" | awk '{ print $2 }')
    if [ -n "${GLANCE_ID}" ] && [ ! -n "${KEEP_GLANCE_IMAGE}" ]; then
        echo "[+] Removing old image..."
        glance image-delete ${GLANCE_ID}
        unset GLANCE_ID
    fi
    if [ ! -n "${GLANCE_ID}" ]; then
        echo "[+] ${IMAGE_PATH}-${SF_VER}.img.qcow2: Uploading glance image..."
        glance image-create --progress --disk-format qcow2 --container-format bare --name sf-${SF_VER} --file ${IMAGE_PATH}-${SF_VER}.img.qcow2
        GLANCE_ID=$(glance image-list | grep "sf-${SF_VER}" | awk '{ print $2 }' | head -n 1)
    else
        echo "[+] Going to re-use glance image uuid ${GLANCE_ID}"
    fi
    NET_ID=$(neutron net-list | grep '\(public\|external_network\)' | awk '{ print $2 }' | head -n 1)
    echo "[+] Starting the stack..."
    (cd deploy/heat; ./deploy.py --arch ${REFARCH_FILE} render)
    heat stack-create --template-file ./deploy/heat/sf-$(basename ${REFARCH_FILE} .yaml).hot \
        -P "image_id=${GLANCE_ID};ext_net_uuid=${NET_ID}" sf_stack || fail "Heat stack-create failed"
    checkpoint "heat-init"
}

function heat_wait {
    echo "[+] Waiting for CREATE_COMPLETE"
    RETRY=200
    while [ $RETRY -gt 0 ]; do
        STACK_STATUS=$(heat stack-show sf_stack | grep 'stack_status ' | awk '{ print $4 }')
        [ "${STACK_STATUS}" != "CREATE_IN_PROGRESS" ] && break
        sleep 6
        let RETRY--
    done
    if [ "${STACK_STATUS}" != "CREATE_COMPLETE" ]; then
        heat stack-show sf_stack
        heat resource-list sf_stack
        fail "Heat stack create failed"
    fi
    echo "ok."
    checkpoint "heat-stack-created"
    STACK_INFO=$(heat stack-show sf_stack)
    export HEAT_IP=$(echo ${STACK_INFO} | sed 's/.*"Public address of the SF instance: \([^"]*\)".*/\1/')
    export HEAT_PASSWORD=$(echo ${STACK_INFO} | sed 's/.*"Administrator password for SF services: \([^"]*\)".*/\1/')
    export HEAT_SLAVE_NETWORK=$(echo ${STACK_INFO} | sed 's/.*"Nodepool slave network: \([^"]*\)".*/\1/')
    if [ ! -n "${HEAT_IP}" ] || [ ! -n "${HEAT_PASSWORD}" ]; then
        fail "Couldn't retrieve stack paramters..."
    fi

    echo "[+] Waiting for ping of ${HEAT_IP}..."
    RETRY=40
    while [ $RETRY -gt 0 ]; do
        ping -c 1 -w 1 ${HEAT_IP} &> /dev/null && break
        sleep 5
        let RETRY--
    done
    [ $RETRY -eq 0 ] && fail "Instance ping failed..."
    echo "ok."
    checkpoint "heat-wait"
}

function build_image {
    if [ -z "${SKIP_BUILD}" ]; then
        echo "[+] Building image ${IMAGE_PATH}"
        ./build_image.sh 2>&1 | tee ${ARTIFACTS_DIR}/image_build.log | grep '(STEP'
        [ "${PIPESTATUS[0]}" == "0" ] || fail "Roles building FAILED" ${ARTIFACTS_DIR}/image_build.log
        [ -f "${IMAGE_PATH}.description_diff" ] && grep "^[><]" ${IMAGE_PATH}.description_diff | grep -v '[><] SF:'
        cp ${IMAGE_PATH}-${SF_VER}.description ${ARTIFACTS_DIR}/
        checkpoint "build_image"
    else
        echo "SKIP_BUILD: Reusing previously built image, just update source code without re-installing"
        echo "            To update requirements and do a full installation, do not use SKIP_BUILD"
        set -e
        sudo rsync -a --delete --no-owner -L config/defaults/ ${IMAGE_PATH}/etc/software-factory/
        sudo rsync -a --delete --no-owner config/ ${IMAGE_PATH}/usr/share/sf-config
        sudo rsync -a --delete --no-owner health-check/ ${IMAGE_PATH}/etc/ansible/health-check/
        sudo rsync -a --delete --no-owner serverspec/ ${IMAGE_PATH}/etc/serverspec/
        sudo rsync -a config/scripts/ ${IMAGE_PATH}/usr/local/bin/
        sudo cp image/edeploy/edeploy ${IMAGE_PATH}/usr/sbin/edeploy
        set +e
    fi
}

function configure_network {
    if [ "${SF_HOST}" != "sftests.com" ]; then
        echo "${SF_HOST} must have ssh key authentitcation and use root user by default"
        return
    fi
    local ip=$1
    rm -f "$HOME/.ssh/known_hosts"
    RETRIES=0
    echo " [+] Starting ssh-keyscan on $ip:22"
    while [ $RETRIES -lt 40 ]; do
        KEY=`ssh-keyscan -p 22 $ip 2> /dev/null`
        if [ "$KEY" != ""  ]; then
            echo $KEY > "$HOME/.ssh/known_hosts"
            echo "  -> $ip:22 is up!"
            break
        fi
        let RETRIES=RETRIES+1
        echo "  [E] ssh-keyscan on $ip:22 failed, will retry in 1 seconds (attempt $RETRIES/40)"
        sleep 1
    done
    [ $RETRIES -eq 40 ] && fail "Can't connect to $ip"
    echo "[+] Avoid ssh error"
    cat << EOF > ${HOME}/.ssh/config
Host ${SF_HOST}
    Hostname ${ip}
    User root
EOF
    chmod 0600 ~/.ssh/config

    echo "[+] Adds ${SF_HOST} to /etc/hosts"
    reset_etc_hosts_dns "${SF_HOST}" ${ip}
    checkpoint "configure_network"
}

function firehose_listen {
    [ -e ${ARTIFACTS_DIR}/firehose.log ] && rm ${ARTIFACTS_DIR}/firehose.log
    echo "Listening to Firehose events..."
    (mosquitto_sub -h sftests.com -t '#' > ${ARTIFACTS_DIR}/firehose.log & );
}

function firehose_check {
    pkill mosquitto_sub
    # TODO very basic checks for now
    echo "Checking Firehose events"
    grep -q -i "review" ${ARTIFACTS_DIR}/firehose.log && echo "Review-type events found"
    grep -q -i "config-update" ${ARTIFACTS_DIR}/firehose.log && echo "config-update related events found"
    grep -q -i "PIPELINE" ${ARTIFACTS_DIR}/firehose.log && echo "Zuul-related events found"
}

function get_logs {
    #This delay is used to wait a bit before fetching log file from hosts
    #in order to not avoid so important logs that can appears some seconds
    #after a failure.
    sleep 2
    set +e

    # Run get_logs from install-server and copy resulting logs
    ssh ${SF_HOST} ansible-playbook /var/lib/software-factory/ansible/get_logs.yml &> ${ARTIFACTS_DIR}/get_logs.log && \
    rsync -avi ${SF_HOST}:sf-logs/ ${ARTIFACTS_DIR}/ &>> ${ARTIFACTS_DIR}/get_logs.log || {
        cat ${ARTIFACTS_DIR}/get_logs.log; echo "get_logs failed...";
    }

    # Copy relevant local file to artifacts_dir
    sudo cp ${IMAGE_PATH}.description ${ARTIFACTS_DIR}/image.description &> /dev/null
    sudo cp ${IMAGE_PATH}.description_diff ${ARTIFACTS_DIR}/image.description_diff &> /dev/null
    [ -d /var/log/selenium ] && cp -r /var/log/selenium/ ${ARTIFACTS_DIR}/selenium
    [ -d /var/log/Xvfb ] && cp -r /var/log/Xvfb/ ${ARTIFACTS_DIR}/Xvfb
    cp -r /tmp/gui/ ${ARTIFACTS_DIR}/screenshots
    # Compress gui test
    (ls /tmp/gui/*.avi 1> /dev/null 2>&1) && gzip -9 ${ARTIFACTS_DIR}/screenshots/*.avi
    (ls /tmp/gui/*.mp* 1> /dev/null 2>&1) && gzip -9 ${ARTIFACTS_DIR}/screenshots/*.mp*

    sudo chown -R ${USER} ${ARTIFACTS_DIR}
    checkpoint "get_logs"
}

function host_debug {
    set +x
    mkdir ${ARTIFACTS_DIR}/host_debug
    sudo dmesg -c > ${ARTIFACTS_DIR}/host_debug/dmesg
    ps aufx >> ${ARTIFACTS_DIR}/host_debug/ps-aufx
    free -m | tee -a ${ARTIFACTS_DIR}/host_debug/free
    sudo df -h | tee -a ${ARTIFACTS_DIR}/host_debug/df
    cat /etc/hosts > ${ARTIFACTS_DIR}/host_debug/hosts
    checkpoint "host_debug"
    [ -z "${DEBUG}" ] || set -x
}

function display_head {
    echo "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
    git log --simplify-merges -n 1 | cat
    echo "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
    echo
}

function fail {
    set +x
    unset DEBUG
    msg=$1
    log_file=$2
    echo -e "\n\n-----8<-------8<------\n  END OF TEST, FAIL: "
    if [ ! -z "$log_file" ] && [ -f "$log_file" ]; then
        echo "=> Log file $log_file --["
        tail -n 500 $log_file
        echo "]--"
    fi
    display_head

    checkpoint "FAIL: $msg"
    host_debug
    [ -z "$SWIFT_artifacts_URL" ] && {
        get_logs
    }
    echo "$0 ${TEST_TYPE}: FAILED (${REFARCH_FILE})"
    exit 1
}

function fetch_bootstraps_data {
    echo "[+] Fetch bootstrap data"
    rm -Rf sf-bootstrap-data
    rsync -a -L ${SF_HOST}:/var/lib/software-factory/bootstrap-data/ sf-bootstrap-data/
    # TODO(2.5.0): remove bellow line
    scp ${SF_HOST}:/etc/ansible/group_vars/all.yaml sf-bootstrap-data/ || :
    scp ${SF_HOST}:/var/lib/software-factory/ansible/group_vars/all.yaml sf-bootstrap-data/ || :
    ADMIN_PASSWORD=$(awk '/admin_password:/ {print $2}' sf-bootstrap-data/all.yaml)
    export REQUESTS_CA_BUNDLE="$(pwd)/sf-bootstrap-data/certs/localCA.pem"
}

function run_bootstraps {
    # Configure lxc host network with container ip 192.168.135.101
    configure_network 192.168.135.101
    eval $(ssh-agent)
    ssh-add ~/.ssh/id_rsa
    echo "$(date) ======= run_bootstraps" | tee -a ${ARTIFACTS_DIR}/bootstraps.log

    ssh ${SF_HOST} python <<SCRIPT
import json
import yaml
import os
f = '/usr/share/sf-config/config-repo/policies/policy.yaml'
if not os.path.isfile(f):
    exit(0)
d = yaml.load(open(f))
d['managesf.project:create'] = 'rule:authenticated_api'
d['managesf.project:delete'] = 'rule:authenticated_api'
json.dump(d, file(f, 'w'), indent=1)
print "POLICY: prepared policy to support project creation by any user..."

f = '/etc/software-factory/sfconfig.yaml'
d = yaml.load(open(f))
d['debug'] = True
yaml.dump(d, open(f, 'w'), default_flow_style=False)
SCRIPT
    CMD="sfconfig.py --skip-install"
    [ "${TEST_TYPE}" == "upgrade" ] && [ "${PREVIOUS_VER}" == "2.4.0" ] && CMD="sfconfig.py"
    ssh -A -tt ${SF_HOST} ${CMD} &> ${ARTIFACTS_DIR}/sfconfig.log \
        && echo "sfconfig.py: SUCCESS"  \
        || { kill -9 $SSH_AGENT_PID; fail "sfconfig.py failed" ${ARTIFACTS_DIR}/sfconfig.log; }
    kill -9 $SSH_AGENT_PID
    checkpoint "run_bootstraps"
    fetch_bootstraps_data
}

function run_heat_bootstraps {
    configure_network ${HEAT_IP}
    RETRY=40
    echo "[+] Waiting for ssh access..."
    # Wait for ssh access
    while [ $RETRY -gt 0 ]; do
        ssh ${SF_HOST} "hostname -f" &> /dev/null && break
        sleep 5
        let RETRY--
    done
    [ $RETRY -eq 0 ] && fail "Couldn't ssh to ${SF_HOST}"
    echo "ok."
    RETRY=300
    echo "[+] Waiting for SUCCESS in cloud-init log..."
    while [ $RETRY -gt 0 ]; do
        ssh ${SF_HOST} "tail /var/log/cloud-init-output.log" 2> /dev/null | grep SUCCESS && break
        sleep 6
        let RETRY--
    done
    [ $RETRY -eq 0 ] && {
        ssh ${SF_HOST} "cat /var/log/cloud-init-output.log"
        fail "Sfconfig.sh didn't finished"
    }
    ssh ${SF_HOST} "tail /var/log/cloud-init-output.log"
    echo "ok."
    checkpoint "run_heat_bootstraps"
    fetch_bootstraps_data
}

function reset_etc_hosts_dns {
    (
        set -x
        host=$1
        ip=$2
        grep -q " ${host}" /etc/hosts || {
            # adds to /etc/hosts if not already defined
            echo "${ip} ${host}" | sudo tee -a /etc/hosts
        } && {
            # else sed in-place
            sudo sed -i "s/^.* ${host}/${ip} ${host}/" /etc/hosts
        }
    ) &> ${ARTIFACTS_DIR}/etc_hosts.log
}

function run_provisioner {
    echo "$(date) ======= run_provisioner"
    if [ "${TEST_TYPE}" == "upgrade" ]; then
        export PROVISIONED_VERSION="${PREVIOUS_VER}"
        # use the actual CA from the current deployment
        rm /tmp/localCA.pem 2> /dev/null
        curl -k https://sftests.com/localCA.pem -o /tmp/localCA.pem
        export REQUESTS_CA_BUNDLE="/tmp/localCA.pem"
    else
        export PROVISIONED_VERSION="${VER}"
    fi
    ./tests/functional/provisioner/provisioner.py 2>> ${ARTIFACTS_DIR}/provisioner.debug || fail "Provisioner failed" ${ARTIFACTS_DIR}/provisioner.debug
    checkpoint "run_provisioner"
}

function run_backup_start {
    echo "$(date) ======= run_backup_start"
    sfmanager --url "${MANAGESF_URL}" --auth "admin:${ADMIN_PASSWORD}" system backup_start || fail "Backup failed"
    sfmanager --url "${MANAGESF_URL}" --auth "admin:${ADMIN_PASSWORD}" system backup_get   || fail "Backup get failed"
    cp sf_backup.tar.gz ${ARTIFACTS_DIR}/
    checkpoint "run_backup_start"
}

function run_backup_restore {
    echo "$(date) ======= run_backup_restore"
    # TODO: replace by sfmanager command
    scp sf_backup.tar.gz ${SF_HOST}:/root/backup.tar.gz
    ssh ${SF_HOST} ansible-playbook -vv -e "backup_file=/root/backup.tar.gz" /var/lib/software-factory/ansible/sf_restore.yml &> ${ARTIFACTS_DIR}/restore.log || fail "Backup restore failed"
    fetch_bootstraps_data
    checkpoint "run_backup_restore"
}

function run_upgrade {
    echo "$(date) ======= run_upgrade"
    INSTALL_SERVER=managesf.${SF_HOST}
    sudo git clone file://$(pwd) /var/lib/lxc/${INSTALL_SERVER}/rootfs/root/software-factory  --depth 1 || fail "Could not clone sf in managesf instance"
    echo "[+] Copying new version (${IMAGE_PATH}/ -> /var/lib/lxc/${INSTALL_SERVER}/rootfs/${IMAGE_PATH})"
    sudo mkdir -p /var/lib/lxc/${INSTALL_SERVER}/rootfs/${IMAGE_PATH}/ || fail "Could not copy ${SF_VER}"
    sudo rsync -a --exclude /usr/src --delete ${IMAGE_PATH}/ /var/lib/lxc/${INSTALL_SERVER}/rootfs/${IMAGE_PATH}/ || fail "Could not copy ${SF_VER}"

    echo "[+] Running upgrade"
    ssh ${SF_HOST} "cd software-factory; ./upgrade.sh" | tee ${ARTIFACTS_DIR}/upgrade.sh.log
    [ "${PIPESTATUS[0]}" != "0" ] && fail "Upgrade failed" "/var/lib/lxc/${INSTALL_SERVER}/rootfs/var/log/software-factory/upgrade.log"
    echo "[+] Update sf-bootstrap-data"
    fetch_bootstraps_data
    echo "[+] Auto submit the auto generated config review after the upgrade"
    review_id=$(./tools/get_last_autogen_upgrade_config_review.py https://${SF_HOST} "Upgrade of base config repository files")
    [ "$review_id" != "0" ] && {
        (
            ssh ${SF_HOST} "cd config; submit_and_wait.py --review-id $review_id --recheck"
            ssh ${SF_HOST} "cd config; submit_and_wait.py --review-id $review_id --approve"
        ) || fail "Could not approve the auto generated config review"
    } || echo "No config review found"

    checkpoint "run_upgrade"
}

function change_fqdn {
    echo "$(date) ======= change_fqdn"
    ssh ${SF_HOST} "sed -i -e 's/fqdn: ${SF_HOST}/fqdn: sftests2.com/g' /etc/software-factory/sfconfig.yaml"
    ssh ${SF_HOST} "sed -i -e 's/${SF_HOST}/sftests2.com/g' /etc/software-factory/arch.yaml"
    checkpoint "change_fqdn"
}

function run_sfconfig {
    echo "$(date) ======= run_sfconfig"
    ssh ${SF_HOST} sfconfig.py --skip-install &> ${ARTIFACTS_DIR}/last_sfconfig.py || fail "sfconfig.py failed" ${ARTIFACTS_DIR}/last_sfconfig.py
    checkpoint "run_sfconfig"
}

function run_checker {
    echo "$(date) ======= run_checker"
    ./tests/functional/provisioner/checker.py $1 2>> ${ARTIFACTS_DIR}/checker.debug || fail "Backup checker failed" ${ARTIFACTS_DIR}/checker.debug
    checkpoint "run_checker"
}

function run_functional_tests {
    echo "$(date) ======= run_functional_tests"
    grep -q "firehose" ${REFARCH_FILE} && firehose_listen
    nosetests --with-timer --with-xunit --logging-format "%(asctime)s: %(levelname)s - %(message)s" -s -v ${SF_TESTS} \
        && echo "Functional tests: SUCCESS" \
        || fail "Functional tests failed" ${ARTIFACTS_DIR}/functional-tests.debug
    grep -q "firehose" ${REFARCH_FILE} && firehose_check
    checkpoint "run_functional_tests"
}

function pre_gui_tests {
    echo "$(date) ======= run_gui_tests"
    echo "Starting Selenium server in background ..."
    ( sudo sh -c '/usr/bin/java -jar /usr/lib/selenium/selenium-server.jar -host 127.0.0.1 >/var/log/selenium/selenium.log 2>/var/log/selenium/error.log' ) &
    if [[ "$DISPLAY" == "localhost"* ]]; then
        echo "X Forwarding detected"
    else
        echo "Starting Xvfb in background ..."
        ( sudo sh -c 'Xvfb :99 -ac -screen 0 1920x1080x24 >/var/log/Xvfb/Xvfb.log 2>/var/log/Xvfb/error.log' ) &
    fi
    mkdir -p /tmp/gui/
}

function post_gui_tests {
    echo "Stopping Xvfb if running ..."
    sudo pkill Xvfb
    echo "Stopping Selenium server ..."
    for i in $(ps ax | grep selenium | awk '{print $1}'); do
        sudo kill $i > /dev/null
    done
}

function run_gui_test {
    export DISPLAY=:99
    # if ffmpeg is installed on the system, record a video
    command -v ffmpeg > /dev/null && tmux new-session -d -s guiTestRecording_$(tr -cd 0-9 </dev/urandom | head -c 3) 'export FFREPORT=file=/tmp/gui/ffmpeg-$(date +%Y%m%s).log && ffmpeg -f x11grab -video_size 1920x1080 -i 127.0.0.1'$DISPLAY' -codec:v mpeg4 -r 16 -vtag xvid -q:v 8 /tmp/gui/'$1'.avi && sleep 5'
    export LC_CTYPE="en_US.UTF-8"
    export LC_ALL="en_US.UTF-8"
    export LANG="en_US.UTF-8"
    locale
    nosetests --with-timer --with-xunit -v $2
    failed=$?
    # stop recording by sending q to ffmpeg process
    command -v ffmpeg > /dev/null && tmux send-keys -t guiTestRecording q
    return $failed
}

function if_gui_tests_failure {
    if [[ "$1" == "1" ]]; then
        fail "GUI tests failed" ${ARTIFACTS_DIR}/gui-tests.debug
    fi
}

function run_serverspec_tests {
    echo "$(date) ======= run_serverspec_tests"
    # Copy current serverspec
    ssh ${SF_HOST} "cd /etc/serverspec; rake spec" 2>&1 | tee ${ARTIFACTS_DIR}/serverspec.output
    [ "${PIPESTATUS[0]}" != "0" ] && fail "Serverspec tests failed"
    checkpoint "run_serverspec_tests"
}

function wait_boot_finished {
    echo "$(date) ======= wait_boot_finished"
    STOP_RETRY=12
    while [ $STOP_RETRY -gt 0 ]; do
        # auditd and ksm are expected to fail on LXC, ignore them
        state=`ssh ${SF_HOST} "systemctl reset-failed auditd ksm ; systemctl is-system-running"`
        [ "${state}" == "running" ] && break
        sleep 5
        let STOP_RETRY--
    done
    checkpoint "wait_boot_finished"
}

START=$(date '+%s')

function checkpoint {
    set +x
    NOW=$(date '+%s')
    ELAPSED=$(python -c "print('%03.2fmin' % (($NOW - $START) / 60.0))")
    echo
    echo "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
    echo "$ELAPSED - $* ($(date))" | sudo tee -a ${ARTIFACTS_DIR}/tests_profiling
    echo "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
    START=$(date '+%s')
    [ -z "${DEBUG}" ] || set -x
}
