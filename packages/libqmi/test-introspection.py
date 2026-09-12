"""Check the generated annotations needed by Python UIM/PDC clients."""
import sys
import xml.etree.ElementTree as ET

ns = {"gi": "http://www.gtk.org/introspection/core/1.0"}
root = ET.parse(sys.argv[1]).getroot()
fields = [
    ("IndicationPdcListConfigsOutputConfigsElement", "id"),
    ("MessageUimGetCardStatusOutputCardStatusCardsElementApplicationsElementV2",
     "application_identifier_value"),
    ("IndicationUimCardStatusOutputCardStatusCardsElementApplicationsElementV2",
     "application_identifier_value"),
]
for record, field in fields:
    element = root.find(
        f"gi:namespace/gi:record[@name='{record}']/gi:field[@name='{field}']/gi:array/gi:type", ns)
    assert element is not None, f"Missing array annotation: {record}.{field}"
    assert element.get("name") == "guint8", (
        f"Wrong element type for {record}.{field}: {element.attrib}")
print("PDC profile IDs and both UIM application-ID arrays are typed as guint8")
