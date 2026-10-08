import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from compare_xlsx import compare

ROOT=Path(__file__).parent
def com_compare(a,b):
    differences=[];excluded=[]
    with zipfile.ZipFile(a) as az,zipfile.ZipFile(b) as bz:
        assert set(az.namelist())==set(bz.namelist())
        for name in az.namelist():
            av,bv=az.read(name),bz.read(name)
            if av==bv:continue
            if not name.endswith('.xml'):
                differences.append(name);continue
            def normalize(value):
                node=ET.fromstring(value)
                for item in node.iter():
                    if item.tag in ('{http://purl.org/dc/terms/}created','{http://purl.org/dc/terms/}modified'):
                        item.text='TIMESTAMP'
                    if item.tag=='{http://schemas.microsoft.com/office/spreadsheetml/2010/11/ac}absPath':item.set('url','OUTPUT_PATH')
                    if item.tag=='{http://schemas.microsoft.com/office/spreadsheetml/2014/revision}revisionPtr':item.set('documentId','GENERATED_ID')
                    for key in list(item.attrib):
                        if key.startswith('{http://schemas.microsoft.com/office/spreadsheetml/') and '/revision' in key and key.endswith('}uid'):
                            item.set(key,'GENERATED_ID')
                return node
            x,y=normalize(av),normalize(bv)
            if name=='xl/calcChain.xml':
                # Excel elige su cadena de cálculo; verificar mismas celdas y hojas.
                equal=Counter((n.get('i'),n.get('r')) for n in x)==Counter((n.get('i'),n.get('r')) for n in y)
            else:equal=ET.tostring(x)==ET.tostring(y)
            (excluded if equal else differences).append(name)
    return {'differences':differences,'normalized_excel_metadata_or_calculation_chain':excluded}

result={}
result['web_report']=compare(ROOT/'before/report.xlsx',ROOT/'after-final/report.xlsx')
result['web_visits']=compare(next((ROOT/'before/visits').rglob('VISITAS*.xlsx')),next((ROOT/'after-final/visits').rglob('VISITAS*.xlsx')))
for filename in ['ZETABURGOS 08-10-26.xlsx','VISITAS 08-10-26.xlsx']:
    result[filename]=com_compare(ROOT/'com-before/reports/08-10-2026'/filename,ROOT/'com-after/reports/08-10-2026'/filename)
assert not result['web_report'] and not result['web_visits']
assert all(not result[n]['differences'] for n in ['ZETABURGOS 08-10-26.xlsx','VISITAS 08-10-26.xlsx'])
(ROOT/'output_comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
