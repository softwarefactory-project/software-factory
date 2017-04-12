#!/usr/bin/python
# Licensed under the Apache License, Version 2.0
#
# Generate ansible group vars based on refarch and sfconfig.yaml

import argparse
import base64
import os
import random
import subprocess
import string
import sys
import time
import uuid
import yaml

from jinja2 import FileSystemLoader
from jinja2.environment import Environment


required_roles = (
    "install-server",
    "gateway",
    "mysql",
    "gerrit",
)


def fail(msg):
    print >>sys.stderr, msg
    exit(1)


def yaml_load(filename):
    try:
        return yaml.safe_load(open(filename))
    except IOError:
        return {}


def yaml_dump(content, fileobj):
    yaml.dump(content, fileobj, default_flow_style=False)


def save_file(content, filename):
    os.rename(filename, "%s.orig" % filename)
    yaml_dump(content, open(filename, "w"))
    print "Updated %s (old version saved to %s)" % (filename,
                                                    "%s.orig" % filename)


def execute(argv):
    if subprocess.Popen(argv).wait():
        raise RuntimeError("Command failed: %s" % argv)


def pread(argv):
    return subprocess.Popen(argv, stdout=subprocess.PIPE).stdout.read()


def encode_image(path):
    return base64.b64encode(open(path).read())


def render_template(dest, template, data):
    with open(dest, "w") as out:
        loader = FileSystemLoader(os.path.dirname(template))
        env = Environment(trim_blocks=True, loader=loader)
        template = env.get_template(os.path.basename(template))
        out.write("%s\n" % template.render(data))
    print("[+] Created %s" % dest)


def load_refarch(filename, domain=None, install_server_ip=None):
    arch = yaml_load(filename)
    # Update domain
    if domain:
        arch["domain"] = domain
    # roles is a dictwith roles name as key and host list as value
    arch["roles"] = {}
    # hosts_files is a dict with host ip as key and hostname list as value
    arch["hosts_file"] = {}
    for host in arch["inventory"]:
        if install_server_ip and "install-server" in host["roles"]:
            host["ip"] = install_server_ip
        elif "ip" not in host:
            fail("%s: host '%s' needs an ip" % (filename, host["name"]))

        host["hostname"] = "%s.%s" % (host["name"], arch["domain"])
        # aliases is a list of cname for this host.
        aliases = set((host['name'],))
        for role in host["roles"]:
            # Add host to role list
            arch["roles"].setdefault(role, []).append(host)
            # Add extra aliases for specific roles
            if role == "gateway":
                aliases.add(arch['domain'])
            elif role == "cauth":
                aliases.add("auth.%s" % arch['domain'])
            # Add role name virtual name (as cname)
            aliases.add("%s.%s" % (role, arch["domain"]))
            aliases.add(role)
        arch["hosts_file"][host["ip"]] = [host["hostname"]] + list(aliases)

    # Check roles
    for requirement in required_roles:
        if requirement not in arch["roles"]:
            fail("%s role is missing" % requirement)
        if len(arch["roles"][requirement]) > 1:
            fail("Only one instance of %s is required" % requirement)

    # Add gateway and install-server hostname/ip for easy access
    gateway_host = arch["roles"]["gateway"][0]
    install_host = arch["roles"]["install-server"][0]
    arch["gateway"] = gateway_host["hostname"]
    arch["gateway_ip"] = gateway_host["ip"]
    arch["install"] = install_host["hostname"]
    arch["install_ip"] = install_host["ip"]
    return arch


def update_sfconfig(data):
    """ This method ensure /etc/software-factory content is upgraded """
    dirty = False
    if not os.path.isfile("/etc/software-factory/logo-topmenu.png"):
        open("/etc/software-factory/logo-topmenu.png", "w").write(
            base64.decodestring(data['theme']['topmenu_logo_data']))
        del data['theme']['topmenu_logo_data']
        dirty = True

    if not os.path.isfile("/etc/software-factory/logo-favicon.ico"):
        open("/etc/software-factory/logo-favicon.ico", "w").write(
            base64.decodestring(data['theme']['favicon_data']))
        del data['theme']['favicon_data']
        dirty = True

    if not os.path.isfile("/etc/software-factory/logo-splash.png"):
        open("/etc/software-factory/logo-splash.png", "w").write(
            base64.decodestring(data['theme']['splash_image_data']))
        del data['theme']['splash_image_data']

    # 2.2.3: remove service list (useless since arch.yaml)
    if 'services' in data:
        del data['services']
        dirty = True

    # Make sure mirrors is in the conf
    if 'mirrors' not in data:
        data['mirrors'] = {
            'swift_mirror_url': 'http://swift:8080/v1/AUTH_uuid/repomirror/',
            'swift_mirror_tempurl_key': 'CHANGEME',
        }
        dirty = True

    # 2.2.4: refactor OAuth2 and OpenID auth config
    if 'oauth2' not in data['authentication']:
        data['authentication']['oauth2'] = {
            'github': {
                'disabled': False,
                'client_id': '',
                'client_secret': '',
                'github_allowed_organizations': ''
            },
            'google': {
                'disabled': False,
                'client_id': '',
                'client_secret': ''
            },
            'bitbucket': {
                'disabled': True,
                'client_id': '',
                'client_secret': ''
            },
        }
        dirty = True

    if 'openid' not in data['authentication']:
        data['authentication']['openid'] = {
            'disabled': False,
            'server': 'https://login.launchpad.net/+openid',
            'login_button_text': 'Log in with the Launchpad service'
        }
        dirty = True

    if data['authentication'].get('github'):
        (data['authentication']['oauth2']
         ['github']['disabled']) = (data['authentication']['github']
                                    ['disabled'])
        (data['authentication']['oauth2']
         ['github']['client_id']) = (data['authentication']['github']
                                     ['github_app_id'])
        (data['authentication']['oauth2']
         ['github']['client_secret']) = (data['authentication']['github']
                                         ['github_app_secret'])
        (data['authentication']['oauth2']['github']
         ['github_allowed_organizations']) = (data['authentication']
                                              ['github']
                                              ['github_allowed_organizations'])
        if data['authentication']['github'].get('redirect_uri'):
            (data['authentication']['oauth2']['github']
             ['redirect_uri']) = string.replace(data['authentication']
                                                ['github']['redirect_uri'],
                                                "login/github/callback",
                                                "login/oauth2/callback")
        del data['authentication']['github']
        dirty = True

    if data['authentication'].get('launchpad'):
        (data['authentication']['openid']
         ['disabled']) = data['authentication']['launchpad']['disabled']
        if data['authentication']['launchpad'].get('redirect_uri'):
            (data['authentication']['openid']
             ['redirect_uri']) = (data['authentication']['launchpad']
                                  ['redirect_uri'])
        del data['authentication']['launchpad']
        dirty = True

    if 'gerrit_connections' not in data:
        data['gerrit_connections'] = []
        dirty = True

    if 'periodic_update' not in data['mirrors']:
        data['mirrors']['periodic_update'] = False
        dirty = True
    if 'swift_mirror_ttl' not in data['mirrors']:
        data['mirrors']['swift_mirror_ttl'] = 15811200
        dirty = True

    if 'use_letsencrypt' not in data['network']:
        data['network']['use_letsencrypt'] = False

    # Mumble is enable when the role is defined in arch
    if 'disabled' in data['mumble']:
        del data['mumble']['disabled']
        dirty = True

    # 2.2.5: finished arch aware top-menu, remove service toggle now
    for hideable in ('redmine', 'etherpad', 'paste'):
        key = 'topmenu_hide_%s' % hideable
        if key in data['theme']:
            del data['theme'][key]
            dirty = True

    # 2.2.6: enforce_ssl is enabled by default
    if 'enforce_ssl' in data['network']:
        del data['network']['enforce_ssl']
        dirty = True

    # 2.2.7: add openid_connect settings
    if 'openid_connect' not in data['authentication']:
        data['authentication']['openid_connect'] = {
            'disabled': True,
            'issuer_url': None,
            'client_secret': None,
            'client_id': None,
            'login_button_text': 'Log in with OpenID Connect'
        }
        dirty = True

    # 2.2.7 rename variables for jinja2 templates
    old_names = ["auth-url", "project-id", "max-servers", "boot-timeout"]
    for value in data['nodepool']['providers']:
        for name in old_names:
            if name in value:
                value[name.replace('-', '_')] = value.pop(name)
                dirty = True

    # 2.2.7: add oidc field mapping, default to google values
    if 'mapping' not in data['authentication']['openid_connect']:
        data['authentication']['openid_connect']['mapping'] = {
            'login': 'email',
            'email': 'email',
            'name': 'name',
            'uid': 'sub',
            'ssh_keys': None
        }

    # 2.3.0: enable static hosts settings
    if 'static_hostnames' not in data['network']:
        data['network']['static_hostnames'] = []
        dirty = True

    # 2.3.0: add debug setting
    if 'debug' not in data:
        data['debug'] = False
        dirty = True

    if "disabled" in data['nodepool']:
        # Disable provider if disable
        if data["nodepool"]["disabled"] and data['nodepool'].get('providers'):
            data['nodepool']['providers'][0]['auth_url'] = ""
        del data['nodepool']['disabled']
        dirty = True

    for provider in data['nodepool'].get('providers', []):
        for key in ('boot_timeout', 'max_servers', 'network', 'pool', 'rate'):
            if key in provider:
                del provider[key]
                dirty = True
        if 'project_id' in provider:
            provider['project_name'] = provider['project_id']
            del provider['project_id']
            dirty = True

    return dirty


def clean_arch(data):
    dirty = False
    # Rename auth in cauth
    for host in data['inventory']:
        if 'auth' in host['roles']:
            host['roles'].remove('auth')
            host['roles'].append('cauth')
            dirty = True
    # Remove data added *IN-PLACE* by utils_refarch
    # Those are now saved in _arch.yaml instead
    for dynamic_key in ("domain", "gateway", "gateway_ip", "install",
                        "install_ip", "ip_prefix", "roles", "hosts_file"):
        if dynamic_key in data:
            del data[dynamic_key]
            dirty = True

    # Remove deployments related information
    for deploy_key in ("cpu", "disk", "mem", "hostid", "rolesname",
                       "hostname"):
        for host in data["inventory"]:
            if deploy_key in host:
                del host[deploy_key]
                dirty = True
    return dirty


def get_sf_version():
    return open("/etc/sf-release").read().strip()


def generate_role_vars(arch, sfconfig, allvars_file, args):
    """ This function 'glue' all roles and convert sfconfig.yaml """
    secrets = yaml_load("%s/secrets.yaml" % args.lib)

    # Cleanup obsolete secrets
    for unused in ("mumble_ice_secret", ):
        if unused in secrets:
            del secrets[unused]

    # Generate all variable when the value is CHANGE_ME
    defaults = {}
    for role in arch["roles"]:
        role_vars = yaml_load("%s/ansible/roles/sf-%s/defaults/main.yml" % (
                              args.share, role))
        defaults.update(role_vars)
        for key, value in role_vars.items():
            if str(value).strip().replace('"', '') == 'CHANGE_ME':
                if key not in secrets:
                    secrets[key] = str(uuid.uuid4())

    # Generate dynamic role variable in the glue dictionary
    glue = {'mysql_databases': {},
            'sf_tasks_dir': "%s/ansible/tasks" % args.share,
            'sf_templates_dir': "%s/templates" % args.share,
            'sf_playbooks_dir': "%s" % args.ansible_root}

    def get_hostname(role):
        if len(arch["roles"][role]) != 1:
            raise RuntimeError("Role %s is defined on multi-host" % role)
        return arch["roles"][role][0]["hostname"]

    def get_or_generate_ssh_key(name):
        priv = "%s/ssh_keys/%s" % (args.lib, name)
        pub = "%s/ssh_keys/%s.pub" % (args.lib, name)

        if not os.path.isfile(priv):
            execute(["ssh-keygen", "-t", "rsa", "-N", "", "-f", priv, "-q"])
        glue[name] = open(priv).read()
        glue["%s_pub" % name] = open(pub).read()

    def get_or_generate_cauth_keys():
        priv_file = "%s/certs/cauth_privkey.pem" % args.lib
        pub_file = "%s/certs/cauth_pubkey.pem" % args.lib
        if not os.path.isfile(priv_file):
            execute(["openssl", "genrsa", "-out", priv_file, "1024"])
        if not os.path.isfile(pub_file):
            execute(["openssl", "rsa", "-in", priv_file, "-out", pub_file,
                     "-pubout"])
        glue["cauth_privkey"] = open(priv_file).read()
        glue["cauth_pubkey"] = open(pub_file).read()

    def get_or_generate_localCA():
        ca_file = "%s/certs/localCA.pem" % args.lib
        ca_key_file = "%s/certs/localCAkey.pem" % args.lib
        ca_srl_file = "%s/certs/localCA.srl" % args.lib
        gateway_cnf = "%s/certs/gateway.cnf" % args.lib
        gateway_key = "%s/certs/gateway.key" % args.lib
        gateway_req = "%s/certs/gateway.req" % args.lib
        gateway_crt = "%s/certs/gateway.crt" % args.lib
        gateway_pem = "%s/certs/gateway.pem" % args.lib

        def xunlink(filename):
            if os.path.isfile(filename):
                os.unlink(filename)

        # First manage CA
        if not os.path.isfile(ca_file):
            # When CA doesn't exists, remove all certificates
            for fn in [gateway_cnf, gateway_req, gateway_crt]:
                xunlink(fn)
            # Generate a random OU subject to be able to trust multiple sf CA
            ou = ''.join(random.choice('0123456789abcdef') for n in xrange(6))
            execute(["openssl", "req", "-nodes", "-days", "3650", "-new",
                     "-x509", "-subj", "/C=FR/O=SoftwareFactory/OU=%s" % ou,
                     "-keyout", ca_key_file, "-out", ca_file])

        if not os.path.isfile(ca_srl_file):
            open(ca_srl_file, "w").write("00\n")

        if os.path.isfile(gateway_cnf) and \
                open(gateway_cnf).read().find("DNS.1 = %s\n" %
                                              sfconfig["fqdn"]) == -1:
            # if FQDN changed, remove all certificates
            for fn in [gateway_cnf, gateway_req, gateway_crt]:
                xunlink(fn)

        # Then manage certificate request
        if not os.path.isfile(gateway_cnf):
            open(gateway_cnf, "w").write("""[req]
req_extensions = v3_req
distinguished_name = req_distinguished_name

[ req_distinguished_name ]
commonName_default = %s

[ v3_req ]
subjectAltName=@alt_names

[alt_names]
DNS.1 = %s
""" % (sfconfig["fqdn"], sfconfig["fqdn"]))

        if not os.path.isfile(gateway_key):
            if os.path.isfile(gateway_req):
                xunlink(gateway_req)
            execute(["openssl", "genrsa", "-out", gateway_key, "2048"])

        if not os.path.isfile(gateway_req):
            if os.path.isfile(gateway_crt):
                xunlink(gateway_crt)
            execute(["openssl", "req", "-new", "-subj",
                     "/C=FR/O=SoftwareFactory/CN=%s" % sfconfig["fqdn"],
                     "-extensions", "v3_req", "-config", gateway_cnf,
                     "-key", gateway_key, "-out", gateway_req])

        if not os.path.isfile(gateway_crt):
            if os.path.isfile(gateway_pem):
                xunlink(gateway_pem)
            execute(["openssl", "x509", "-req", "-days", "3650",
                     "-extensions", "v3_req", "-extfile", gateway_cnf,
                     "-CA", ca_file, "-CAkey", ca_key_file,
                     "-CAserial", ca_srl_file,
                     "-in", gateway_req, "-out", gateway_crt])

        if not os.path.isfile(gateway_pem):
            open(gateway_pem, "w").write("%s\n%s\n" % (
                open(gateway_key).read(), open(gateway_crt).read()))

        glue["localCA_pem"] = open(ca_file).read()
        glue["gateway_crt"] = open(gateway_crt).read()
        glue["gateway_key"] = open(gateway_key).read()
        glue["gateway_chain"] = glue["gateway_crt"]

    glue["gateway_url"] = "https://%s" % sfconfig["fqdn"]
    glue["sf_version"] = get_sf_version()

    if sfconfig["debug"]:
        for service in ("managesf", "zuul", "nodepool"):
            glue["%s_loglevel" % service] = "DEBUG"
            glue["%s_root_loglevel" % service] = "INFO"

    if "cauth" in arch["roles"]:
        get_or_generate_cauth_keys()

    if "gateway" in arch["roles"]:
        get_or_generate_localCA()
        glue["gateway_topmenu_logo_data"] = encode_image(
            "/etc/software-factory/logo-topmenu.png")
        glue["gateway_favicon_data"] = encode_image(
            "/etc/software-factory/logo-favicon.ico")
        glue["gateway_splash_image_data"] = encode_image(
            "/etc/software-factory/logo-splash.png")

    if "install-server" in arch["roles"]:
        get_or_generate_ssh_key("service_rsa")

    if "mysql" in arch["roles"]:
        glue["mysql_host"] = get_hostname("mysql")

    if "cauth" in arch["roles"]:
        glue["cauth_mysql_host"] = get_hostname("mysql")
        glue["mysql_databases"]["cauth"] = {
            'hosts': ['localhost', get_hostname("cauth")],
            'user': 'cauth',
            'password': secrets['cauth_mysql_password'],
        }

    if "managesf" in arch["roles"]:
        glue["managesf_internal_url"] = "http://%s:%s" % (
            get_hostname("managesf"), defaults["managesf_port"])
        glue["managesf_mysql_host"] = get_hostname("mysql")
        glue["mysql_databases"]["managesf"] = {
            'hosts': ['localhost', get_hostname("managesf")],
            'user': 'managesf',
            'password': secrets['managesf_mysql_password'],
        }

    if "gerrit" in arch["roles"]:
        glue["gerrit_host"] = get_hostname("gerrit")
        glue["gerrit_pub_url"] = "%s/r/" % glue["gateway_url"]
        glue["gerrit_internal_url"] = "http://%s:%s/r/" % (
            get_hostname("gerrit"), defaults["gerrit_port"])
        glue["gerrit_email"] = "gerrit@%s" % sfconfig["fqdn"]
        glue["gerrit_mysql_host"] = glue["mysql_host"]
        glue["mysql_databases"]["gerrit"] = {
            'hosts': list(set(('localhost',
                               get_hostname("gerrit"),
                               get_hostname("managesf")))),
            'user': 'gerrit',
            'password': secrets['gerrit_mysql_password'],
        }
        get_or_generate_ssh_key("gerrit_service_rsa")
        get_or_generate_ssh_key("gerrit_admin_rsa")

    if "zuul" in arch["roles"]:
        if ("nodepool" not in arch["roles"] or
            len(sfconfig["nodepool"].get("providers", [])) == 0 or (
                len(sfconfig["nodepool"]["providers"]) == 1 and
                not sfconfig["nodepool"]["providers"][0]["auth_url"])):
            glue["zuul_offline_node_when_complete"] = False
        glue["zuul_pub_url"] = "%s/zuul/" % glue["gateway_url"]
        glue["zuul_internal_url"] = "http://%s:%s/" % (
            get_hostname("zuul"), defaults["zuul_port"])

    if "nodepool" in arch["roles"]:
        glue["nodepool_providers"] = sfconfig["nodepool"].get("providers", [])
        glue["nodepool_mysql_host"] = glue["mysql_host"]
        glue["mysql_databases"]["nodepool"] = {
            'hosts': ["localhost", get_hostname("nodepool")],
            'user': 'nodepool',
            'password': secrets['nodepool_mysql_password'],
        }

    if "jenkins" in arch["roles"]:
        glue["jenkins_host"] = get_hostname("jenkins")
        glue["jenkins_internal_url"] = "http://%s:%s/jenkins/" % (
            get_hostname("jenkins"), defaults["jenkins_http_port"])
        glue["jenkins_api_url"] = "http://%s:%s/jenkins/" % (
            get_hostname("jenkins"), defaults["jenkins_api_port"])
        glue["jenkins_pub_url"] = "%s/jenkins/" % glue["gateway_url"]
        get_or_generate_ssh_key("jenkins_rsa")

    if "firehose" in arch["roles"]:
        glue["firehose_host"] = get_hostname("firehose")

    if "grafana" in arch["roles"]:
        glue["grafana_internal_url"] = "http://%s:%s/" % (
            get_hostname("grafana"), defaults["grafana_http_port"])
        glue["grafana_mysql_host"] = get_hostname("mysql")
        glue["mysql_databases"]["grafana"] = {
            'hosts': ['localhost', get_hostname("grafana")],
            'user': 'grafana',
            'password': secrets['grafana_mysql_password'],
        }

    if "influxdb" in arch["roles"]:
        glue["influxdb_host"] = get_hostname("influxdb")

    if "lodgeit" in arch["roles"]:
        glue["lodgeit_mysql_host"] = get_hostname("mysql")
        glue["mysql_databases"]["lodgeit"] = {
            'hosts': ['localhost', get_hostname("lodgeit")],
            'user': 'lodgeit',
            'password': secrets['lodgeit_mysql_password'],
        }

    if "etherpad" in arch["roles"]:
        glue["etherpad_mysql_host"] = get_hostname("mysql")
        glue["mysql_databases"]["etherpad"] = {
            'hosts': ['localhost', get_hostname("etherpad")],
            'user': 'etherpad',
            'password': secrets['etherpad_mysql_password'],
        }

    if "storyboard" in arch["roles"]:
        glue["storyboard_mysql_host"] = glue["mysql_host"]
        glue["mysql_databases"]["storyboard"] = {
            'hosts': ["localhost", get_hostname("storyboard")],
            'user': 'storyboard',
            'password': secrets["storyboard_mysql_password"],
        }

    if "murmur" in arch["roles"]:
        if sfconfig["mumble"].get("password"):
            glue["murmur_password"] = sfconfig["mumble"].get("password")

    # Save secrets to new secrets file
    yaml_dump(secrets, open("%s/secrets.yaml" % args.lib, "w"))
    # And add them to the all.yaml file
    yaml_dump(secrets, allvars_file)
    # Add glue to the all.yaml.file
    yaml_dump(glue, allvars_file)


def generate_inventory_and_playbooks(arch, ansible_root, share):
    # Adds playbooks to architecture
    firehose = "firehose" in arch["roles"]
    for host in arch["inventory"]:
        host["rolesname"] = map(lambda x: "sf-%s" % x, host["roles"])
    # Merge nodepool/nodepool-builder role
    for host in arch["inventory"]:
        for role in host["rolesname"]:
            if role == "sf-nodepool":
                host.setdefault("nodepool_services", []).append("nodepool")
            elif role == "sf-nodepool-builder":
                host.setdefault("nodepool_services", []).append(
                    "nodepool-builder")
            elif role == "sf-zuul":
                host.setdefault("zuul_services", []).append("zuul")
            elif role == "sf-zuul-merger":
                host.setdefault("zuul_services", []).append("zuul-merger")

        # Remove meta roles
        if "sf-nodepool-builder" in host["rolesname"]:
            host["rolesname"].remove("sf-nodepool-builder")
            # Make sure the base role is present
            if "sf-nodepool" not in host["rolesname"]:
                host["rolesname"].append("sf-nodepool")
        if "sf-zuul-merger" in host["rolesname"]:
            host["rolesname"].remove("sf-zuul-merger")
            # Make sure the base role is present
            if "sf-zuul" not in host["rolesname"]:
                host["rolesname"].append("sf-zuul")

        # if firehose role is in the arch, install ochlero where needed
        if firehose:
            if "zuul" in host["roles"] or "nodepool" in host["roles"]:
                host["rolesname"].append("sf-ochlero")

    templates = "%s/templates" % share

    # Generate inventory
    render_template("%s/hosts" % ansible_root,
                    "%s/inventory.j2" % templates,
                    arch)

    # Generate playbooks
    for playbooks in ("sf_install", "sf_setup", "sf_postconf",
                      "sf_configrepo_update",
                      "get_logs", "sf_backup", "sf_restore"):
        render_template("%s/%s.yml" % (ansible_root, playbooks),
                        "%s/%s.yml.j2" % (templates, playbooks),
                        arch)

    # Generate server spec hosts file
    render_template("/etc/serverspec/hosts.yaml",
                    "%s/serverspec.yml.j2" % templates,
                    arch)

    # Generate /etc/hosts file
    render_template("/etc/hosts",
                    "%s/etc-hosts.j2" % templates,
                    arch)


def usage():
    p = argparse.ArgumentParser()
    # inputs
    p.add_argument("--arch", default="/etc/software-factory/arch.yaml",
                   help="The architecture file")
    p.add_argument("--sfconfig", default="/etc/software-factory/sfconfig.yaml",
                   help="The configuration file")
    p.add_argument("--extra", default="/etc/software-factory/custom-vars.yaml",
                   help="Extra ansible variable file")
    p.add_argument("--share", default="/usr/share/sf-config",
                   help="Templates and ansible roles")
    # outputs
    p.add_argument("--ansible_root",
                   default="/var/lib/software-factory/ansible",
                   help="Generated playbook output directory")
    p.add_argument("--lib", default="/var/lib/software-factory/bootstrap-data",
                   help="Deployment secrets output directory")
    # tunning
    p.add_argument("--skip-install", default=False, action='store_true',
                   help="Do not call install tasks")
    p.add_argument("--skip-setup", default=False, action='store_true',
                   help="Do not call setup tasks")
    return p.parse_args()


def main():
    args = usage()

    if not args.skip_setup:
        execute(["logger", "sfconfig.py: started"])
        print("[%s] Running sfconfig.py" % time.ctime())

    # Create required directories
    allyaml = "%s/group_vars/all.yaml" % args.ansible_root
    for dirname in (args.ansible_root,
                    "%s/group_vars" % args.ansible_root,
                    "%s/facts" % args.ansible_root,
                    args.lib,
                    "%s/ssh_keys" % args.lib,
                    "%s/certs" % args.lib):
        if not os.path.isdir(dirname):
            os.makedirs(dirname, 0o700)
    if os.path.islink(allyaml):
        # Remove previously created link to sfconfig.yaml
        os.unlink(allyaml)

    # Make sure the yaml files are updated
    sfconfig = yaml_load(args.sfconfig)
    sfarch = yaml_load(args.arch)
    if update_sfconfig(sfconfig):
        save_file(sfconfig, args.sfconfig)
    if clean_arch(sfarch):
        save_file(sfarch, args.arch)

    # Process the arch file and render playbooks
    local_ip = pread(["ip", "route", "get", "8.8.8.8"]).split()[6]
    arch = load_refarch(args.arch, sfconfig['fqdn'], local_ip)
    generate_inventory_and_playbooks(arch, args.ansible_root, args.share)

    # Generate group vars
    with open(allyaml, "w") as allvars_file:
        generate_role_vars(arch, sfconfig, allvars_file, args)
        allvars_file.write("###### Legacy content ######\n")
        allvars_file.write(open(args.sfconfig).read())
        if os.path.isfile(args.extra):
            allvars_file.write(open(args.extra).read())
        yaml_dump(arch, allvars_file)

    print("[+] %s written!" % allyaml)
    os.environ["ANSIBLE_CONFIG"] = "/usr/share/sf-config/ansible/ansible.cfg"
    if not args.skip_install:
        execute(["ansible-playbook",
                 "/var/lib/software-factory/ansible/sf_install.yml"])
    if not args.skip_setup:
        execute(["ansible-playbook",
                 "/var/lib/software-factory/ansible/sf_setup.yml"])
        execute(["logger", "sfconfig.py: ended"])
        print("""%s: SUCCESS

Access dashboard: https://%s
Login with admin user, get the admin password by running:
  awk '/admin_password/ {print $2}' /etc/software-factory/sfconfig.yaml

""" % (sfconfig['fqdn'], sfconfig['fqdn']))


if __name__ == "__main__":
    main()
