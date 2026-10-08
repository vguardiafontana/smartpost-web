"""Compara todos los componentes XLSX, excluyendo sólo fecha de guardado/creación."""
import json
from pathlib import Path
import sys
import zipfile
import xml.etree.ElementTree as ET


def compare(left, right):
    mismatches=[]
    with zipfile.ZipFile(left) as a, zipfile.ZipFile(right) as b:
        if set(a.namelist()) != set(b.namelist()):
            return ['componentes diferentes']
        for name in a.namelist():
            av,bv=a.read(name),b.read(name)
            if name=='docProps/core.xml':
                def without_time(value):
                    root=ET.fromstring(value)
                    for node in list(root):
                        if node.tag in ('{http://purl.org/dc/terms/}created','{http://purl.org/dc/terms/}modified'):
                            root.remove(node)
                    return ET.tostring(root)
                av,bv=without_time(av),without_time(bv)
            if av!=bv:mismatches.append(name)
    return mismatches

if __name__=='__main__':
    differences=compare(Path(sys.argv[1]),Path(sys.argv[2]))
    print(json.dumps({'different_parts':differences,'equal':not differences}))
    sys.exit(bool(differences))
