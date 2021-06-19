import json
import os
import re
from collections import defaultdict, OrderedDict

import tenacity
import requests

from .. import config
from ..messages import *
from .updateCrossRefsLegacy import legacyFetchHeadings


def progressMessager(index, total):
    return lambda: say(f"Downloading data for spec {index}/{total}...")


def update(path, dryRun=False):
    say("Downloading specifications data...")
    specs = fetchSpecData()
    if not specs:
        return
    routingData = fetchRoutingData()


    anchors = defaultdict(list)
    lastMsgTime = 0

    for i, spec in enumerate(specs.values(), 1):
        lastMsgTime = config.doEvery(
            s=5,
            lastTime=lastMsgTime,
            action=progressMessager(i, len(specs)),
        )
        specs[spec["vshortname"]] = spec

        route = routingData[spec["vshortname"]]
        if "current_dfns" in route:
            data = fetchDfns("ed/"+route["current_dfns"])
            if not data:
                continue
            addToAnchors(data, anchors, spec=spec, status="current")
        if "snapshot_dfns" in route and spec["snapshot_url"] is not None:
            data = fetchDfns("tr/"+route["snapshot_dfns"])
            if not data:
                continue
            addToAnchors(data, anchors, spec=spec, status="snapshot")
        '''
        # Reffy headings data is currently broken for multipage specs
        if "current_headings" in route:
            data = fetchHeadings("ed/"+route["current_headings"])
            if not data:
                continue
            addToHeadings(data, headings, spec=spec, status="current")
        if "snapshot_headings" in route:
            data = fetchHeadings("tr/"+route["snapshot_headings"])
            if not data:
                continue
            addToHeadings(data, anchors, spec=spec, status="snapshot")
        '''

    headings = legacyFetchHeadings()

    methods = extractMethodData(anchors)
    fors = extractForsData(anchors)

    if not dryRun:
        writtenPaths = set()
        try:
            p = os.path.join(path, "specs.json")
            writtenPaths.add(p)
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps(specs, ensure_ascii=False, indent=2, sort_keys=True))
        except Exception as e:
            die("Couldn't save spec database to disk.\n{0}", e)
            return
        try:
            for spec, specHeadings in headings.items():
                p = os.path.join(path, "headings", f"headings-{spec}.json")
                writtenPaths.add(p)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            specHeadings, ensure_ascii=False, indent=2, sort_keys=True
                        )
                    )
        except Exception as e:
            die("Couldn't save headings database to disk.\n{0}", e)
            return
        try:
            writtenPaths.update(writeAnchorsFile(anchors, path))
        except Exception as e:
            die("Couldn't save anchor database to disk.\n{0}", e)
            return
        try:
            p = os.path.join(path, "methods.json")
            writtenPaths.add(p)
            with open(p, "w", encoding="utf-8") as f:
                f.write(
                    json.dumps(methods, ensure_ascii=False, indent=2, sort_keys=True)
                )
        except Exception as e:
            die("Couldn't save methods database to disk.\n{0}", e)
            return
        try:
            p = os.path.join(path, "fors.json")
            writtenPaths.add(p)
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps(fors, ensure_ascii=False, indent=2, sort_keys=True))
        except Exception as e:
            die("Couldn't save fors database to disk.\n{0}", e)
            return

    say("Success!")
    return writtenPaths






@tenacity.retry(
    reraise=True, stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_random(1, 2)
)
def fetchSpecData():
    try:
        response = requests.get(
            "https://raw.githubusercontent.com/w3c/browser-specs/master/index.json"
        )
    except Exception as e:
        die("Couldn't download the specifications data.\n{0}", e)
        return

    try:
        rawSpecData = response.json(encoding="utf-8", object_pairs_hook=OrderedDict)
    except Exception as e:
        die(
            "The specifications data wasn't valid JSON for some reason. Try downloading again?\n{0}",
            e,
        )
        return

    specs = dict()
    for rawSpec in rawSpecData:
        spec = specFromRaw(rawSpec)
        specs[spec["vshortname"]] = spec
    return specs

def specFromRaw(rawSpec):
    spec = {}
    spec["vshortname"] = rawSpec["shortname"].lower()
    spec["title"] = rawSpec["shortTitle"]
    spec["description"] = rawSpec["title"]
    spec["current_url"] = rawSpec["nightly"]["url"]
    if "release" in rawSpec:
        spec["snapshot_url"] = rawSpec["release"]["url"]
    else:
        spec["snapshot_url"] = None
    if rawSpec["series"]["shortname"] != spec["vshortname"]:
        spec["shortname"] = rawSpec["series"]["shortname"].lower()
    else:
        spec["shortname"] = rawSpec["shortname"].lower()
    if "seriesVersion" in rawSpec:
        spec["version"] = rawSpec["seriesVersion"]
    else:
        spec["version"] = "1"
    spec["delta"] = rawSpec["seriesComposition"] == "delta"
    if "tests" in rawSpec:
        spec["tests"] = rawSpec["tests"]
    else:
        spec["tests"] = {}

    return spec





@tenacity.retry(
    reraise=True, stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_random(1, 2)
)
def fetchRoutingData():
    try:
        edResponse = requests.get(
            "https://raw.githubusercontent.com/w3c/webref/master/ed/index.json"
        )
        trResponse = requests.get(
            "https://raw.githubusercontent.com/w3c/webref/master/tr/index.json"
        )
    except Exception as e:
        die("Couldn't download the specification routing data.\n{0}", e)
        return

    try:
        edRouting = edResponse.json(encoding="utf-8", object_pairs_hook=OrderedDict)
        trRouting = trResponse.json(encoding="utf-8", object_pairs_hook=OrderedDict)
    except Exception as e:
        die(
            "The specification routing data wasn't valid JSON for some reason. Try downloading again?\n{0}",
            e,
        )
        return

    routes = dict()
    for raw in edRouting["results"]:
        shortname = raw["shortname"].lower()
        data = routes.setdefault(shortname, {})
        if "dfns" in raw:
            data["current_dfns"] = raw["dfns"]
        if "headings" in raw:
            data["current_headings"] = raw["headings"]
    for raw in trRouting["results"]:
        shortname = raw["shortname"].lower()
        data = routes.setdefault(shortname, {})
        if "dfns" in raw:
            data["snapshot_dfns"] = raw["dfns"]
        if "headings" in raw:
            data["snapshot_headings"] = raw["headings"]

    return routes



@tenacity.retry(
    reraise=True, stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_random(1, 2)
)
def fetchDfns(path):
    try:
        response = requests.get(
            "https://raw.githubusercontent.com/w3c/webref/master/" + path
        )
    except Exception as e:
        die(f"Couldn't download the {path} data.\n{e}")
        return

    try:
        return response.json(encoding="utf-8", object_pairs_hook=OrderedDict)["dfns"]
    except Exception as e:
        die(
            f"The {path} data wasn't valid JSON for some reason. Try downloading again?\n{e}",
        )
        return


def fixupAnchor(anchor):
    """Miscellaneous fixes to the anchors before I start processing"""

    # This one issue was annoying
    if anchor.get("title", None) == "'@import'":
        anchor["title"] = "@import"

    # If any smart quotes crept in, replace them with ASCII.
    linkingTexts = anchor.get("linking_text", [anchor.get("title")])
    for i, t in enumerate(linkingTexts):
        if t is None:
            continue
        if "’" in t or "‘" in t:
            t = re.sub(r"‘|’", "'", t)
            linkingTexts[i] = t
        if "“" in t or "”" in t:
            t = re.sub(r"“|”", '"', t)
            linkingTexts[i] = t
    anchor["linking_text"] = linkingTexts

    # Normalize whitespace to a single space
    for k, v in list(anchor.items()):
        if isinstance(v, str):
            anchor[k] = re.sub(r"\s+", " ", v.strip())
        elif isinstance(v, list):
            for k1, v1 in enumerate(v):
                if isinstance(v1, str):
                    anchor[k][k1] = re.sub(r"\s+", " ", v1.strip())
    return anchor


def addToHeadings(rawAnchor, specHeadings, spec):
    return
    uri = rawAnchor["uri"]
    if uri[0] == "#":
        # Either single-page spec, or link on the top page of a multi-page spec
        heading = {
            "url": spec["{}_url".format(rawAnchor["status"])] + uri,
            "number": rawAnchor["name"]
            if re.match(r"[\d.]+$", rawAnchor["name"])
            else "",
            "text": rawAnchor["title"],
            "spec": spec["title"],
        }
        fragment = uri
        shorthand = "/" + fragment
    else:
        # Multi-page spec, need to guard against colliding IDs
        if "#" in uri:
            # url to a heading in the page, like "foo.html#bar"
            match = re.match(r"([\w-]+).*?(#.*)", uri)
            if not match:
                die(
                    "Unexpected URI pattern '{0}' for spec '{1}'. Please report this to the Bikeshed maintainer.",
                    uri,
                    spec["vshortname"],
                )
                return
            page, fragment = match.groups()
            page = "/" + page
        else:
            # url to a page itself, like "foo.html"
            page, _, _ = uri.partition(".")
            page = "/" + page
            fragment = "#"
        shorthand = page + fragment
        heading = {
            "url": spec["{}_url".format(rawAnchor["status"])] + uri,
            "number": rawAnchor["name"]
            if re.match(r"[\d.]+$", rawAnchor["name"])
            else "",
            "text": rawAnchor["title"],
            "spec": spec["title"],
        }
    if shorthand not in specHeadings:
        specHeadings[shorthand] = {}
    specHeadings[shorthand][rawAnchor["status"]] = heading
    if fragment not in specHeadings:
        specHeadings[fragment] = []
    if shorthand not in specHeadings[fragment]:
        specHeadings[fragment].append(shorthand)


def cleanSpecHeadings(headings):
    """Headings data was purposely verbose, assuming collisions even when there wasn't one.
    Want to keep the collision data for multi-page, so I can tell when you request a non-existent page,
    but need to collapse away the collision stuff for single-page."""
    for specHeadings in headings.values():
        for k, v in list(specHeadings.items()):
            if k[0] == "#" and len(v) == 1 and v[0][0:2] == "/#":
                # No collision, and this is either a single-page spec or a non-colliding front-page link
                # Go ahead and collapse them.
                specHeadings[k] = specHeadings[v[0]]
                del specHeadings[v[0]]


def addToAnchors(rawAnchors, anchors, spec, status):
    for rawAnchor in rawAnchors:
        anchor = {
            "status": status,
            "type": rawAnchor["type"],
            "spec": spec["vshortname"],
            "shortname": spec["shortname"],
            "version": spec["version"],
            "export": rawAnchor["access"] == "public",
            "normative": not rawAnchor["informative"],
            "url": rawAnchor["href"],
            "for": rawAnchor["for"],
        }
        for text in rawAnchor["linkingText"]:
            if anchor["type"] in config.lowercaseTypes:
                text = text.lower()
            text = re.sub(r"\s+", " ", text)
            anchors[text].append(anchor)


def extractMethodData(anchors):
    """Compile a db of {argless methods => {argfull method => {args, fors, url, shortname}}"""

    methods = defaultdict(dict)
    for key, anchors_ in anchors.items():
        # Extract the name and arguments
        match = re.match(r"([^(]+)\((.*)\)", key)
        if not match:
            continue
        methodName, argstring = match.groups()
        arglessMethod = methodName + "()"
        args = [x.strip() for x in argstring.split(",")] if argstring else []
        for anchor in anchors_:
            if anchor["type"] not in config.idlMethodTypes:
                continue
            if key not in methods[arglessMethod]:
                methods[arglessMethod][key] = {
                    "args": args,
                    "for": set(),
                    "shortname": anchor["shortname"],
                }
            methods[arglessMethod][key]["for"].update(anchor["for"])
    # Translate the "for" set back to a list for JSONing
    for signatures in methods.values():
        for signature in signatures.values():
            signature["for"] = sorted(signature["for"])
    return methods


def extractForsData(anchors):
    """Compile a db of {for value => dict terms that use that for value}"""

    fors = defaultdict(set)
    for key, anchors_ in anchors.items():
        for anchor in anchors_:
            for for_ in anchor["for"]:
                if for_ == "":
                    continue
                fors[for_].add(key)
            if not anchor["for"]:
                fors["/"].add(key)
    for key, val in list(fors.items()):
        fors[key] = sorted(val)
    return fors


def writeAnchorsFile(anchors, path):
    """
    Keys may be duplicated.

    key
    type
    spec
    shortname
    level
    status
    url
    export (boolish string)
    normative (boolish string)
    for* (one per line, unknown #)
    - (by itself, ends the segment)
    """
    writtenPaths = set()
    groupedEntries = defaultdict(dict)
    for key, entries in anchors.items():
        group = config.groupFromKey(key)
        groupedEntries[group][key] = entries
    for group, group_anchors in groupedEntries.items():
        p = os.path.join(path, "anchors", f"anchors-{group}.data")
        writtenPaths.add(p)
        with open(p, "w", encoding="utf-8") as fh:
            for key, entries in sorted(group_anchors.items(), key=lambda x: x[0]):
                for e in entries:
                    fh.write(key + "\n")
                    for field in [
                        "type",
                        "spec",
                        "shortname",
                        "version",
                        "status",
                        "url",
                    ]:
                        fh.write(str(e.get(field, "")) + "\n")
                    for field in ["export", "normative"]:
                        if e.get(field, False):
                            fh.write("1\n")
                        else:
                            fh.write("\n")
                    for forValue in e.get("for", []):
                        if forValue:  # skip empty strings
                            fh.write(forValue + "\n")
                    fh.write("-" + "\n")
    return writtenPaths
