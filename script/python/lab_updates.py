"""Incremental edits to owned Docker laboratories, with bounded recovery.

The persisted topology remains the last accepted topology until all changes
succeed. A failed update requires cleanup even when recovery succeeds: shell
state and packets in flight cannot be rolled back.
"""
import copy
import ipaddress
import json
import shutil
import tempfile
from pathlib import Path

from lab_devices import LabError, device_root


def runtime_signature(topology):
    return {
        "nodes": sorted(({key: sorted(value, key=lambda port: port["name"]) if key == "ports" else value
                          for key, value in node.items() if key not in ("x", "y", "width", "height")}
                         for node in topology["nodes"]), key=lambda n: n["id"]),
        "links": sorted(topology["links"], key=lambda link: link["id"]),
    }


def interfaces(manager, record, node_id):
    return {row["ifname"]: row for row in json.loads(
        manager.ns(record, node_id, "ip", "-j", "-d", "link", "show"))}


def link_rows(manager, record, link, created=None):
    rows = {}
    for side in ("a", "b"):
        end = link[side]
        row = interfaces(manager, record, end["node"]).get(end["port"], {})
        alias = "route-ovs:" + record["runtime"]["deployment"] + ":" + link["id"] + ":" + side
        valid_alias = row.get("ifalias") == alias
        if created is not None:
            # A freshly created pair can fail before both aliases are set.
            valid_alias = row.get("ifalias", "") in ("", alias) and row.get("ifindex") == created[side]["ifindex"]
        if not valid_alias or row.get("linkinfo", {}).get("info_kind") != "veth":
            raise LabError("接口归属已变化，拒绝修改: " + end["node"] + "." + end["port"])
        rows[side] = row
    if (rows["a"].get("link_index") != rows["b"].get("ifindex") or
            rows["b"].get("link_index") != rows["a"].get("ifindex")):
        raise LabError("veth 对端已变化，拒绝修改: " + link["id"])
    return rows


def plan_update(manager, record, target):
    old = {n["id"]: n for n in record["topology"]["nodes"]}
    new = {n["id"]: n for n in target["nodes"]}
    recreate_keys = ("name", "kind", "template", "image", "command", "config")
    rebuilt = {nid for nid in old.keys() & new.keys()
               if any(old[nid].get(key) != new[nid].get(key) for key in recreate_keys)}
    remove_nodes = (old.keys() - new.keys()) | rebuilt
    add_nodes = (new.keys() - old.keys()) | rebuilt
    old_links = {link["id"]: link for link in record["topology"]["links"]}
    new_links = {link["id"]: link for link in target["links"]}
    remove_links = [link for lid, link in old_links.items()
                    if new_links.get(lid) != link or any(link[s]["node"] in rebuilt for s in ("a", "b"))]
    add_links = [link for lid, link in new_links.items()
                 if old_links.get(lid) != link or any(link[s]["node"] in rebuilt for s in ("a", "b"))]
    # Every existing resource is validated before the first mutation, including
    # resources that are not changing. Repeat these checks immediately before use.
    inventory = {nid: interfaces(manager, record, nid) for nid in old}
    for link in old_links.values():
        link_rows(manager, record, link)
    released = {(link[s]["node"], link[s]["port"]) for link in remove_links for s in ("a", "b")}
    for link in add_links:
        for side in ("a", "b"):
            end = link[side]
            if end["node"] in old and end["node"] not in rebuilt:
                if end["port"] in inventory[end["node"]] and (end["node"], end["port"]) not in released:
                    raise LabError("接口已被其他配置占用，拒绝覆盖: " + end["node"] + "." + end["port"])
    for image in sorted({new[nid]["image"] for nid in add_nodes}):
        try:
            manager.dock("image", "inspect", image)
        except LabError as exc:
            raise LabError("本机没有可用镜像 " + image) from exc
    return {"old": old, "new": new, "remove_nodes": sorted(remove_nodes), "add_nodes": sorted(add_nodes),
            "remove_links": remove_links, "add_links": add_links}


def create_node(manager, record, node, journal):
    from lab_core import LABEL  # Constants only; called after both modules load.
    name = "rov-{}-{}".format(record["topology"]["id"], node["id"])
    args = ["create", "--name", name, "--hostname", node["name"], "--network", "none",
            "--label", LABEL + "=" + record["topology"]["id"],
            "--label", LABEL + ".deployment=" + record["runtime"]["deployment"],
            "--label", LABEL + ".node=" + node["id"],
            "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW"]
    adapter = manager.adapter(node)
    args += adapter.prepare(manager, record, node)
    cid = manager.dock(*(args + [node["image"]] + adapter.command(node)))
    record["runtime"]["nodes"][node["id"]] = {"id": cid, "name": name, "pid": 0}
    journal.append(node["id"])
    manager.write(record)
    manager.dock("start", cid)
    item = manager.live(record, node["id"])
    record["runtime"]["nodes"][node["id"]]["pid"] = item["State"]["Pid"]
    manager.write(record)
    manager.ns(record, node["id"], "ip", "link", "set", "lo", "up")
    adapter.started(manager, record, node)
    manager.note(record, "创建设备 " + node["name"])


def remove_node(manager, record, node_id):
    from lab_core import LABEL
    saved = record["runtime"]["nodes"][node_id]
    item = manager.owned(record, manager.inspect(saved["id"]))
    if (item.get("Config", {}).get("Labels") or {}).get(LABEL + ".node") != node_id:
        raise LabError("设备节点归属不匹配，拒绝移除: " + node_id)
    manager.dock("rm", "-f", "-v", item["Id"])
    del record["runtime"]["nodes"][node_id]
    manager.note(record, "移除设备 " + node_id + "，已保存配置目录保留")


def create_link(manager, record, link, journal):
    a, b = link["a"], link["b"]
    ca, cb = manager.live(record, a["node"]), manager.live(record, b["node"])
    # Check names again: a shell can create an interface after the preflight.
    for end in (a, b):
        if end["port"] in interfaces(manager, record, end["node"]):
            raise LabError("接口已存在，拒绝覆盖: " + end["node"] + "." + end["port"])
    manager.run("ip", "link", "add", "name", a["port"], "netns", str(ca["State"]["Pid"]),
                "type", "veth", "peer", "name", b["port"], "netns", str(cb["State"]["Pid"]))
    entry = {"link": link, "ends": None}
    journal.append(entry)
    entry["ends"] = {s: interfaces(manager, record, link[s]["node"])[link[s]["port"]] for s in ("a", "b")}
    for side in ("a", "b"):
        end = link[side]
        manager.ns(record, end["node"], "ip", "link", "set", "dev", end["port"],
                   "alias", "route-ovs:" + record["runtime"]["deployment"] + ":" + link["id"] + ":" + side)
        manager.ns(record, end["node"], "ip", "link", "set", "dev", end["port"], "up")
    manager.note(record, "连接 {}.{} ↔ {}.{}".format(a["node"], a["port"], b["node"], b["port"]))


def remove_link(manager, record, link, created=None):
    link_rows(manager, record, link, created)
    end = link["a"]
    manager.ns(record, end["node"], "ip", "link", "delete", "dev", end["port"])
    manager.note(record, "断开网线 " + link["id"])


def connected_ports(topology):
    return {(link[s]["node"], link[s]["port"]) for link in topology["links"] for s in ("a", "b")}


def gateway_port(node, connected):
    if not node.get("gateway"):
        return None
    gateway = ipaddress.ip_address(node["gateway"])
    return next((port["name"] for port in node["ports"] if port["address"] and
                 (node["id"], port["name"]) in connected and gateway in ipaddress.ip_interface(port["address"]).network), None)


def sync_network(manager, record, old_topology, new_topology, fresh):
    old_nodes = {n["id"]: n for n in old_topology["nodes"]}
    old_connected, connected = connected_ports(old_topology), connected_ports(new_topology)
    for node in new_topology["nodes"]:
        nid = node["id"]
        old = old_nodes.get(nid, {})
        previous = {p["name"]: p["address"] for p in old.get("ports", [])}
        for port in node["ports"]:
            pair = (nid, port["name"])
            if pair not in connected:
                continue
            if pair not in fresh and previous.get(port["name"], "") == port["address"]:
                continue
            if manager.template(node).get("adapter") == "linux-bridge":
                manager.ns(record, nid, "ip", "link", "set", "dev", port["name"], "master", "br0")
            else:
                old_address = previous.get(port["name"], "") if pair not in fresh else ""
                if old_address and old_address != port["address"]:
                    rows = json.loads(manager.ns(record, nid, "ip", "-j", "addr", "show", "dev", port["name"]))
                    actual = {str(info.get("local")) + "/" + str(info.get("prefixlen")) for row in rows for info in row.get("addr_info", [])}
                    if old_address in actual:
                        manager.ns(record, nid, "ip", "addr", "del", old_address, "dev", port["name"])
                if port["address"]:
                    manager.ns(record, nid, "ip", "addr", "replace", port["address"], "dev", port["name"])
        old_port = gateway_port(old, old_connected) if old else None
        new_port = gateway_port(node, connected)
        if (old.get("gateway", ""), old_port) == (node["gateway"], new_port) and (nid, new_port) not in fresh:
            continue
        if old.get("gateway") and old_port:
            family = "-6" if ":" in old["gateway"] else "-4"
            routes = json.loads(manager.ns(record, nid, "ip", family, "-j", "route", "show", "default"))
            if any(route.get("gateway") == old["gateway"] and route.get("dev") == old_port for route in routes):
                manager.ns(record, nid, "ip", family, "route", "del", "default", "via", old["gateway"], "dev", old_port)
        if new_port:
            family = "-6" if ":" in node["gateway"] else "-4"
            manager.ns(record, nid, "ip", family, "route", "replace", "default", "via", node["gateway"], "dev", new_port)


def restore_config(manager, lab_id, node_id, backup):
    destination = device_root(manager, lab_id, node_id)
    # Shared files can have been replaced by the container. Never copy through
    # existing files/symlinks: prepare a separate tree, then rename directories.
    replacement = backup.parent / ("restore-" + node_id)
    shutil.copytree(backup, replacement, symlinks=True)
    displaced = backup.parent / ("displaced-" + node_id)
    if destination.exists():
        destination.rename(displaced)
    try:
        replacement.rename(destination)
    except Exception:
        if displaced.exists() and not destination.exists():
            displaced.rename(destination)
        raise


def apply_update(manager, record, target):
    plan = plan_update(manager, record, target)
    old_topology = copy.deepcopy(record["topology"])
    added_nodes, added_links, removed_nodes, removed_links = [], [], [], []
    with tempfile.TemporaryDirectory(prefix=".update-", dir=manager.directory) as temporary:
        backups = {}
        for nid in plan["add_nodes"]:
            source = device_root(manager, target["id"], nid)
            if source.exists():
                destination = Path(temporary) / nid
                shutil.copytree(source, destination, symlinks=True)
                backups[nid] = destination
        try:
            manager.note(record, "开始应用拓扑；仅重建启动属性变化的设备，未变化容器保持运行")
            for link in plan["remove_links"]:
                remove_link(manager, record, link)
                removed_links.append(link)
            for nid in plan["remove_nodes"]:
                remove_node(manager, record, nid)
                removed_nodes.append(nid)
            for nid in plan["add_nodes"]:
                create_node(manager, record, plan["new"][nid], added_nodes)
            for link in plan["add_links"]:
                create_link(manager, record, link, added_links)
            fresh = {(link[s]["node"], link[s]["port"]) for link in plan["add_links"] for s in ("a", "b")}
            sync_network(manager, record, old_topology, target, fresh)
            for nid in added_nodes:
                manager.adapter(plan["new"][nid]).linked(manager, record, plan["new"][nid])
            for nid in sorted({nid for nid, _ in fresh} - set(added_nodes)):
                manager.adapter(plan["new"][nid]).link_added(manager, record, plan["new"][nid])
            for nid in plan["new"]:
                manager.live(record, nid)
            for link in target["links"]:
                link_rows(manager, record, link)
            record["topology"] = target
            record["runtime"].update(phase="running", error="")
            manager.note(record, "拓扑更新完成；未连接端口的地址保留，接线后应用")
        except Exception as exc:
            record["topology"] = old_topology
            errors = []
            manager.note(record, "应用失败，尝试恢复原拓扑: " + str(exc))
            def recover(operation):
                try:
                    operation()
                except Exception as error:
                    errors.append(str(error))
            for entry in reversed(added_links):
                if entry["ends"] is None:
                    errors.append("新网线未能记录接口身份，需清理设备")
                else:
                    recover(lambda entry=entry: remove_link(manager, record, entry["link"], entry["ends"]))
            for nid in reversed(added_nodes):
                recover(lambda nid=nid: remove_node(manager, record, nid))
            for nid, backup in backups.items():
                if nid in added_nodes and nid in record["runtime"]["nodes"]:
                    errors.append("设备未能停止，未替换其共享配置目录: " + nid)
                else:
                    recover(lambda nid=nid, backup=backup: restore_config(manager, target["id"], nid, backup))
            for nid in removed_nodes:
                if nid not in record["runtime"]["nodes"]:
                    recover(lambda nid=nid: create_node(manager, record, plan["old"][nid], []))
            for link in removed_links:
                recover(lambda link=link: create_link(manager, record, link, []))
            fresh = {(link[s]["node"], link[s]["port"]) for link in removed_links for s in ("a", "b")}
            recover(lambda: sync_network(manager, record, target, old_topology, fresh))
            for nid in removed_nodes:
                recover(lambda nid=nid: manager.adapter(plan["old"][nid]).linked(manager, record, plan["old"][nid]))
            message = str(exc) + ("；恢复未完成: " + "；".join(errors) if errors else "；已尝试恢复原设备和网线")
            raise LabError(message + "。原拓扑保留，请清理后重新部署；未保存的运行状态不能保证恢复") from exc
