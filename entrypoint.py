import base64
import hashlib
import pprint
import json
import os
import random
import re
import shlex
import string
import subprocess
import time
import uuid

import click
import consulate
from M2Crypto.EVP import Cipher


# Default charset
_DEFAULT_CHARS = "".join([string.ascii_uppercase,
                          string.digits,
                          string.lowercase])


def get_random_chars(size=12, chars=_DEFAULT_CHARS):
    """Generates random characters.
    """
    return ''.join(random.choice(chars) for _ in range(size))


def ldap_encode(password):
    # borrowed from community-edition-setup project
    # see http://git.io/vIRex
    salt = os.urandom(4)
    sha = hashlib.sha1(password)
    sha.update(salt)
    b64encoded = '{0}{1}'.format(sha.digest(), salt).encode('base64').strip()
    encrypted_password = '{{SSHA}}{0}'.format(b64encoded)
    return encrypted_password


def get_quad():
    # borrowed from community-edition-setup project
    # see http://git.io/he1p
    return str(uuid.uuid4())[:4].upper()


def encrypt_text(text, key):
    # Porting from pyDes-based encryption (see http://git.io/htxa)
    # to use M2Crypto instead (see https://gist.github.com/mrluanma/917014)
    cipher = Cipher(alg="des_ede3_ecb",
                    key=b"{}".format(key),
                    op=1,
                    iv="\0" * 16)
    encrypted_text = cipher.update(b"{}".format(text))
    encrypted_text += cipher.final()
    return base64.b64encode(encrypted_text)


def decrypt_text(encrypted_text, key):
    # Porting from pyDes-based encryption (see http://git.io/htpk)
    # to use M2Crypto instead (see https://gist.github.com/mrluanma/917014)
    cipher = Cipher(alg="des_ede3_ecb",
                    key=b"{}".format(key),
                    op=0,
                    iv="\0" * 16)
    decrypted_text = cipher.update(base64.b64decode(
        b"{}".format(encrypted_text)
    ))
    decrypted_text += cipher.final()
    return decrypted_text


def reindent(text, num_spaces=1):
    text = [(num_spaces * " ") + line.lstrip() for line in text.splitlines()]
    text = "\n".join(text)
    return text


def safe_render(text, ctx):
    text = re.sub(r"%([^\(])", r"%%\1", text)
    # There was a % at the end?
    text = re.sub(r"%$", r"%%", text)
    return text % ctx


def generate_base64_contents(text, num_spaces=1):
    text = text.encode("base64").strip()
    if num_spaces > 0:
        text = reindent(text, num_spaces)
    return text


def get_sys_random_chars(size=12, chars=_DEFAULT_CHARS):
    """Generates random characters based on OS.
    """
    return ''.join(random.SystemRandom().choice(chars) for _ in range(size))


def join_quad_str(x):
    return ".".join([get_quad() for _ in xrange(x)])


def safe_inum_str(x):
    return x.replace("@", "").replace("!", "").replace(".", "")


def encode_template(fn, ctx, base_dir="/opt/config-init/templates"):
    path = os.path.join(base_dir, fn)
    with open(path) as f:
        return generate_base64_contents(safe_render(f.read(), ctx))


def exec_cmd(cmd):
    args = shlex.split(cmd)
    popen = subprocess.Popen(args,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
    stdout, stderr = popen.communicate()
    retcode = popen.returncode
    return stdout, stderr, retcode


def generate_openid_keys(passwd, jks_path, jwks_path, dn, exp=365,
                         alg="RS256 RS384 RS512 ES256 ES384 ES512"):
    if os.path.exists(jks_path):
        os.unlink(jks_path)

    if os.path.exists(jwks_path):
        os.unlink(jwks_path)

    cmd = " ".join([
        "java",
        "-jar", "/opt/config-init/javalibs/keygen.jar",
        "-enc_keys", alg,
        "-sig_keys", alg,
        "-dnname", "{!r}".format(dn),
        "-expiration", "{}".format(exp),
        "-keystore", jks_path,
        "-keypasswd", passwd,
    ])
    out, err, retcode = exec_cmd(cmd)
    if retcode == 0:
        with open(jwks_path, "w") as f:
            f.write(out)
    return out


def encode_keys_template(jks_pass, jks_fn, jwks_fn, cfg):
    pubkey = generate_openid_keys(
        jks_pass, jks_fn, jwks_fn, cfg["default_openid_jks_dn_name"])
    base_dir, fn = os.path.split(jwks_fn)
    return encode_template(fn, cfg, base_dir=base_dir), pubkey


def generate_config(admin_pw, email, domain, org_name, country_code, state, city,
                    encoded_salt="", encoded_ox_ldap_pw="", inum_appliance="",
                    oxauth_jks_pw="", ldap_type="opendj"):
    cfg = {}

    # use external encoded_salt if defined; fallback to auto-generated value
    cfg["encoded_salt"] = encoded_salt or get_random_chars(24)
    cfg["orgName"] = org_name
    cfg["country_code"] = country_code
    cfg["state"] = state
    cfg["city"] = city
    cfg["hostname"] = domain
    cfg["admin_email"] = email
    cfg["default_openid_jks_dn_name"] = "CN=oxAuth CA Certificates"

    cfg["pairwiseCalculationKey"] = get_sys_random_chars(
        random.randint(20, 30))

    cfg["pairwiseCalculationSalt"] = get_sys_random_chars(
        random.randint(20, 30))

    cfg["shibJksFn"] = "/etc/certs/shibIDP.jks"
    cfg["shibJksPass"] = get_random_chars()

    cfg["encoded_shib_jks_pw"] = encrypt_text(
        cfg["shibJksPass"], cfg["encoded_salt"])

    cfg["shibboleth_version"] = "v3"
    cfg["idp3Folder"] = "/opt/shibboleth-idp"
    cfg["jetty_base"] = "/opt/gluu/jetty"

    # ====
    # LDAP
    # ====
    cfg["ldap_init_host"] = ""  # need to be populated from somewhere else
    cfg["ldap_init_port"] = ""  # need to be populated from somewhere else
    cfg["ldap_port"] = 1389
    cfg["ldaps_port"] = 1636

    cfg["ldap_binddn"] = "cn=directory manager"  # for OpenDJ
    cfg["ldap_site_binddn"] = "cn=directory manager"
    cfg["opendj_p12_pass"] = get_random_chars()
    cfg["ldapTrustStoreFn"] = "/etc/certs/opendj.pkcs12"
    cfg["encoded_ldapTrustStorePass"] = encrypt_text(cfg["opendj_p12_pass"], cfg["encoded_salt"])

    # if ldap_type == "openldap":
    #     cfg["ldap_binddn"] += ",o=gluu"  # for OpenLDAP
    #     cfg["ldap_site_binddn"] += ",o=site"  # for OpenLDAP
    #     cfg["ldapTrustStoreFn"] = "/etc/certs/openldap.pkcs12"

    cfg["encoded_ldap_pw"] = ldap_encode(admin_pw)

    # use external encoded_ox_ldap_pw if defined; fallback to auto-generate value
    cfg["encoded_ox_ldap_pw"] = encoded_ox_ldap_pw or encrypt_text(admin_pw, cfg["encoded_salt"])
    cfg["ldap_use_ssl"] = False
    cfg["replication_cn"] = "replicator"
    cfg["replication_dn"] = "cn={},o=gluu".format(cfg["replication_cn"])
    cfg["encoded_replication_pw"] = cfg["encoded_ldap_pw"]
    cfg["encoded_ox_replication_pw"] = cfg["encoded_ox_ldap_pw"]

    # ====
    # Inum
    # ====
    cfg["baseInum"] = "@!{}".format(join_quad_str(4))
    cfg["inumOrg"] = "{}!0001!{}".format(cfg["baseInum"], join_quad_str(2))
    cfg["inumOrgFN"] = safe_inum_str(cfg["inumOrg"])

    # use external inumAppliance if defined; fallback to auto-generate value
    cfg["inumAppliance"] = inum_appliance or "{}!0002!{}".format(
        cfg["baseInum"], join_quad_str(2))

    cfg["inumApplianceFN"] = safe_inum_str(cfg["inumAppliance"])

    # ======
    # oxAuth
    # ======
    cfg["oxauth_client_id"] = "{}!0008!{}".format(
        cfg["inumOrg"], join_quad_str(2))

    cfg["oxauthClient_encoded_pw"] = encrypt_text(
        get_random_chars(), cfg["encoded_salt"])

    cfg["oxauth_openid_jks_fn"] = "/etc/certs/oxauth-keys.jks"
    # use external oxauth_openid_jks_pass if defined; fallback to auto-generate value
    cfg["oxauth_openid_jks_pass"] = oxauth_jks_pw or get_random_chars()
    cfg["oxauth_openid_jwks_fn"] = "/etc/certs/oxauth-keys.json"

    cfg["oxauth_config_base64"] = encode_template(
        "oxauth-config.json", cfg)

    cfg["oxauth_static_conf_base64"] = encode_template(
        "oxauth-static-conf.json", cfg)

    cfg["oxauth_error_base64"] = encode_template("oxauth-errors.json", cfg)

    # if oxauth-keys.jks is not exist, generate them
    if not os.path.exists(cfg["oxauth_openid_jks_fn"]):
        cfg["oxauth_openid_key_base64"], _ = encode_keys_template(
            cfg["oxauth_openid_jks_pass"],
            cfg["oxauth_openid_jks_fn"],
            cfg["oxauth_openid_jwks_fn"],
            cfg,
        )

    # oxAuth keys
    cfg["oxauth_key_rotated_at"] = int(time.time())
    with open(cfg["oxauth_openid_jks_fn"]) as fr:
        cfg["oxauth_jks_base64"] = encrypt_text(fr.read(), cfg["encoded_salt"])

    # =======
    # SCIM RS
    # =======
    cfg["scim_rs_client_id"] = "{}!0008!{}".format(
        cfg["inumOrg"], join_quad_str(2))

    cfg["scim_rs_client_jks_fn"] = "/etc/certs/scim-rs.jks"
    cfg["scim_rs_client_jwks_fn"] = "/etc/certs/scim-rs-keys.json"
    cfg["scim_rs_client_jks_pass"] = get_random_chars()

    cfg["scim_rs_client_jks_pass_encoded"] = encrypt_text(
        cfg["scim_rs_client_jks_pass"], cfg["encoded_salt"])

    cfg["scim_rs_client_base64_jwks"], _ = encode_keys_template(
        cfg["scim_rs_client_jks_pass"],
        cfg["scim_rs_client_jks_fn"],
        cfg["scim_rs_client_jwks_fn"],
        cfg,
    )

    with open(cfg["scim_rs_client_jks_fn"]) as fr:
        cfg["scim_rs_jks_base64"] = encrypt_text(fr.read(), cfg["encoded_salt"])

    # =======
    # SCIM RP
    # =======
    cfg["scim_rp_client_id"] = "{}!0008!{}".format(
        cfg["inumOrg"], join_quad_str(2))

    cfg["scim_rp_client_jks_fn"] = "/etc/certs/scim-rp.jks"
    cfg["scim_rp_client_jwks_fn"] = "/etc/certs/scim-rp-keys.json"
    cfg["scim_rp_client_jks_pass"] = get_random_chars()

    cfg["scim_rp_client_jks_pass_encoded"] = encrypt_text(
        cfg["scim_rp_client_jks_pass"], cfg["encoded_salt"])

    cfg["scim_rp_client_base64_jwks"], _ = encode_keys_template(
        cfg["scim_rp_client_jks_pass"],
        cfg["scim_rp_client_jks_fn"],
        cfg["scim_rp_client_jwks_fn"],
        cfg,
    )

    with open(cfg["scim_rp_client_jks_fn"]) as fr:
        cfg["scim_rp_jks_base64"] = encrypt_text(fr.read(), cfg["encoded_salt"])

    # ===========
    # Passport RS
    # ===========
    cfg["passport_rs_client_id"] = "{}!0008!{}".format(
        cfg["inumOrg"], join_quad_str(2))

    cfg["passport_rs_client_jks_fn"] = "/etc/certs/passport-rs.jks"
    cfg["passport_rs_client_jwks_fn"] = "/etc/certs/passport-rs-keys.json"
    cfg["passport_rs_client_jks_pass"] = get_random_chars()

    cfg["passport_rs_client_jks_pass_encoded"] = encrypt_text(
        cfg["passport_rs_client_jks_pass"], cfg["encoded_salt"])

    cfg["passport_rs_client_base64_jwks"], _ = encode_keys_template(
        cfg["passport_rs_client_jks_pass"],
        cfg["passport_rs_client_jks_fn"],
        cfg["passport_rs_client_jwks_fn"],
        cfg,
    )

    # ===========
    # Passport RP
    # ===========
    cfg["passport_rp_client_id"] = "{}!0008!{}".format(
        cfg["inumOrg"], join_quad_str(2))

    cfg["passport_rp_client_jks_pass"] = get_random_chars()
    cfg["passport_rp_client_jks_fn"] = "/etc/certs/passport-rp.jks"
    cfg["passport_rp_client_jwks_fn"] = "/etc/certs/passport-rp-keys.json"
    cfg["passport_rp_client_cert_fn"] = "/etc/certs/passport-rp.pem"
    cfg["passport_rp_client_cert_alg"] = "RS512"

    cfg["passport_rp_client_base64_jwks"], pubkey = encode_keys_template(
        cfg["passport_rp_client_jks_pass"],
        cfg["passport_rp_client_jks_fn"],
        cfg["passport_rp_client_jwks_fn"],
        cfg,
    )

    for key in json.loads(pubkey)["keys"]:
        if key["alg"] == cfg["passport_rp_client_cert_alg"]:
            cfg["passport_rp_client_cert_alias"] = key["kid"]

    # =====
    # oxIDP
    # =====
    cfg["oxidp_config_base64"] = encode_template("oxidp-config.json", cfg)

    # ========
    # oxAsimba
    # ========
    cfg["oxasimba_config_base64"] = encode_template(
        "oxasimba-config.json", cfg)

    # ================
    # SSL cert and key
    # ================
    ssl_cert = "/etc/certs/gluu_https.crt"
    ssl_key = "/etc/certs/gluu_https.key"

    # generate self-signed SSL cert and key only if they aren't exist
    if not(os.path.exists(ssl_cert) and os.path.exists(ssl_key)):
        generate_ssl_certkey("gluu_https", admin_pw, email, domain, org_name, country_code, state, city)

    with open(ssl_cert) as f:
        cfg["ssl_cert"] = f.read()

    with open(ssl_key) as f:
        cfg["ssl_key"] = f.read()

    # ================
    # Extension config
    # ================
    ext_cfg = get_extension_config()
    cfg.update(ext_cfg)

    # ===========================
    # IDP3 Signing and encryption
    # ===========================
    idp3_signing_cert = "/etc/certs/idp-signing.crt"
    # idp3_signing_key = "/etc/certs/idp-signing.key"
    generate_ssl_certkey("idp-signing", admin_pw, email, domain, org_name, country_code, state, city)
    with open(idp3_signing_cert) as f:
        cfg["idp3SigningCertificateText"] = f.read()

    idp3_encryption_cert = "/etc/certs/idp-encryption.crt"
    # idp3_encryption_key = "/etc/certs/idp-encryption.key"
    generate_ssl_certkey("idp-encryption", admin_pw, email, domain, org_name, country_code, state, city)
    with open(idp3_encryption_cert) as f:
        cfg["idp3EncryptionCertificateText"] = f.read()

    # populated config
    return cfg


def generate_ssl_certkey(suffix, admin_pw, email, domain, org_name,
                         country_code, state, city):
    # create key with password
    _, err, retcode = exec_cmd(
        "openssl genrsa -des3 -out /etc/certs/{}.key.orig "
        "-passout pass:'{}' 2048".format(suffix, admin_pw))
    assert retcode == 0, "Failed to generate SSL key with password; reason={}".format(err)

    # create .key
    _, err, retcode = exec_cmd(
        "openssl rsa -in /etc/certs/{0}.key.orig "
        "-passin pass:'{1}' -out /etc/certs/{0}.key".format(suffix, admin_pw))
    assert retcode == 0, "Failed to generate SSL key; reason={}".format(err)

    # create .csr
    _, err, retcode = exec_cmd(
        "openssl req -new -key /etc/certs/{0}.key "
        "-out /etc/certs/{0}.csr "
        "-subj /C='{1}'/ST='{2}'/L='{3}'/O='{4}'/CN='{5}'/emailAddress='{6}'".format(suffix, country_code, state, city, org_name, domain, email))
    assert retcode == 0, "Failed to generate SSL CSR; reason={}".format(err)

    # create .crt
    _, err, retcode = exec_cmd(
        "openssl x509 -req -days 365 -in /etc/certs/{0}.csr "
        "-signkey /etc/certs/{0}.key -out /etc/certs/{0}.crt".format(suffix))
    assert retcode == 0, "Failed to generate SSL cert; reason={}".format(err)

    # return the paths
    return "/etc/certs/{}.crt".format(suffix), "/etc/certs/{}.key".format(suffix)


def get_extension_config(basedir="/opt/config-init/static/extension"):
    cfg = {}
    for ext_type in os.listdir(basedir):
        ext_type_dir = os.path.join(basedir, ext_type)

        for fname in os.listdir(ext_type_dir):
            filepath = os.path.join(ext_type_dir, fname)
            ext_name = "{}_{}".format(ext_type, os.path.splitext(fname)[0].lower())

            with open(filepath) as fd:
                cfg[ext_name] = generate_base64_contents(fd.read())
    return cfg


def validate_country_code(ctx, param, value):
    if len(value) != 2:
        raise click.BadParameter("Country code must be two characters")
    return value


@click.command()
@click.option("--admin-pw", required=True, help="Password for admin access.")
@click.option("--email", required=True, help="Email for support.")
@click.option("--domain", required=True, help="Domain for Gluu Server.")
@click.option("--org-name", required=True, help="Organization name.")
@click.option("--country-code", required=True, help="Country code.", callback=validate_country_code)
@click.option("--state", required=True, help="State.")
@click.option("--city", required=True, help="City.")
@click.option("--kv-host", default="localhost", help="Hostname/IP address of KV store.", show_default=True)
@click.option("--kv-port", default=8500, help="Port of KV store.", show_default=True)
@click.option("--save", default=False, help="Save config to KV store.", is_flag=True)
@click.option("--view", default=False, help="Show generated config.", is_flag=True)
@click.option("--encoded-salt", default="", help="Encoded salt.", show_default=True)
@click.option("--encoded-ox-ldap-pw", default="", help="Encoded ox LDAP password.", show_default=True)
@click.option("--inum-appliance", default="", help="Inum Appliance.", show_default=True)
@click.option("--oxauth-jks-pw", default="", help="oxAuth OpenID JKS password.", show_default=True)
def main(admin_pw, email, domain, org_name, country_code, state, city,
         kv_host, kv_port, save, view, encoded_salt, encoded_ox_ldap_pw,
         inum_appliance, oxauth_jks_pw):

    consul = consulate.Consul(host=kv_host, port=kv_port)

    if save:
        # generate all config
        cfg = generate_config(
            admin_pw, email, domain, org_name, country_code, state, city,
            encoded_salt, encoded_ox_ldap_pw, inum_appliance, oxauth_jks_pw,
        )
        for k, v in cfg.iteritems():
            if k not in consul.kv:
                consul.kv.set(k, v)
    else:
        cfg = dict(consul.kv)

    if view:
        pprint.pprint(cfg)


if __name__ == "__main__":
    main()
