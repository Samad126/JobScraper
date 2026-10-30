"""Find technologies (the "stack") mentioned in a post, locally, without any AI tokens.

Add your own at the bottom of TECHNOLOGIES: (display name, regex). Patterns use lookarounds instead of \\b
so names like ".NET", "C#" and "C++" match. Case-sensitive ones are marked, to avoid words like "go" or "swift".
"""
import re

_B = r"(?<![\w.#+])"  # not glued to the end of another word
_E = r"(?![\w#+])"     # not glued to the start of another word

# (name, pattern, case_sensitive)
TECHNOLOGIES = [
    # languages
    (".NET", r"\.NET|ASP\.NET|dotnet|\.Net Core|NET(?=\s+(?:Developer|Intern|Engineer|Core))", False),
    ("C#", r"C#|C Sharp", False),
    ("C++", r"C\+\+", False),
    ("Java", r"Java(?!\s*Script)", True),
    ("JavaScript", r"Java\s?Script|\bJS\b", False),
    ("TypeScript", r"Type\s?Script", False),
    ("Python", r"Python", False),
    ("PHP", r"PHP", True),
    ("Go", r"Golang|Go\s+(?:lang|developer|dev)", True),
    ("Rust", r"Rust", True),
    ("Kotlin", r"Kotlin", False),
    ("Swift", r"Swift(?:UI)?", True),
    ("Ruby", r"Ruby(?: on Rails)?", True),
    ("Scala", r"Scala", True),
    ("Dart", r"Dart", True),
    ("Bash", r"Bash|Shell script", False),
    ("PowerShell", r"Power\s?Shell", False),
    # frontend / mobile
    ("React", r"React(?!\s*Native)(?:\.js|JS)?", True),
    ("React Native", r"React\s*Native", False),
    ("Angular", r"Angular(?:JS)?", True),
    ("Vue", r"Vue(?:\.js|JS)?", True),
    ("Next.js", r"Next\.?js", False),
    ("Node.js", r"Node\.?js|NodeJS", False),
    ("Flutter", r"Flutter", False),
    ("Android", r"Android", True),
    ("iOS", r"iOS", True),
    ("HTML/CSS", r"HTML|CSS", True),
    # backend / frameworks
    ("Spring", r"Spring(?:\s?Boot)?", True),
    ("Django", r"Django", False),
    ("Flask", r"Flask", True),
    ("FastAPI", r"FastAPI", False),
    ("Laravel", r"Laravel", False),
    ("Symfony", r"Symfony", False),
    ("NestJS", r"Nest\.?js", False),
    ("Entity Framework", r"Entity\s?Framework|EF Core", False),
    ("REST API", r"REST(?:ful)?(?:\s?API)?", True),
    ("GraphQL", r"GraphQL", False),
    ("gRPC", r"gRPC", False),
    ("Microservices", r"microservice", False),
    # data
    ("SQL", r"(?<!MS )SQL(?!\s?Server)|T-SQL|PL/SQL", True),
    ("SQL Server", r"MS\s?SQL|SQL\s?Server|MSSQL", False),
    ("PostgreSQL", r"Postgre(?:SQL|s)?", False),
    ("MySQL", r"MySQL|MariaDB", False),
    ("Oracle", r"Oracle", True),
    ("MongoDB", r"Mongo(?:DB)?", False),
    ("Redis", r"Redis", False),
    ("Elasticsearch", r"Elastic\s?search|ELK", False),
    ("Kafka", r"Kafka", False),
    ("RabbitMQ", r"RabbitMQ", False),
    ("Spark", r"(?:Apache\s)?Spark", True),
    ("Airflow", r"Airflow", False),
    ("Power BI", r"Power\s?BI", False),
    ("Tableau", r"Tableau", False),
    ("Excel", r"Excel", False),
    ("ETL", r"ETL", True),
    # cloud / devops
    ("AWS", r"AWS|Amazon Web Services", True),
    ("Azure", r"Azure", False),
    ("GCP", r"GCP|Google Cloud", True),
    ("Docker", r"Docker", False),
    ("Kubernetes", r"Kubernetes|K8s", False),
    ("Terraform", r"Terraform", False),
    ("Ansible", r"Ansible", False),
    ("Jenkins", r"Jenkins", False),
    ("GitLab", r"GitLab", False),
    ("GitHub", r"GitHub", False),
    ("Git", r"Git", True),
    ("CI/CD", r"CI\s?/\s?CD", True),
    ("Linux", r"Linux|Ubuntu|CentOS|RedHat|Red Hat", False),
    ("Windows Server", r"Windows\s?Server", False),
    ("VMware", r"VMware", False),
    ("Nginx", r"Nginx", False),
    ("Zabbix", r"Zabbix", False),
    ("Grafana", r"Grafana", False),
    ("Prometheus", r"Prometheus", False),
    # network / security
    ("Active Directory", r"Active\s?Directory", False),
    ("Cisco", r"Cisco", False),
    ("Fortinet", r"Fortinet|FortiGate", False),
    ("Palo Alto", r"Palo\s?Alto", False),
    ("SIEM", r"SIEM", True),
    ("Splunk", r"Splunk", False),
    ("Wazuh", r"Wazuh", False),
    ("QRadar", r"QRadar", False),
    ("Firewall", r"Firewall", False),
    ("Pentest", r"Pentest|Penetration\s?Test", False),
    ("ISO 27001", r"ISO\s?/?\s?(?:IEC\s)?27001", False),
    # QA
    ("Selenium", r"Selenium", False),
    ("Cypress", r"Cypress", False),
    ("Playwright", r"Playwright", False),
    ("Postman", r"Postman", False),
    ("JMeter", r"JMeter", False),
    ("Appium", r"Appium", False),
    ("Jira", r"Jira", False),
    # business systems
    ("SAP", r"SAP", True),
    ("1C", r"1C", True),
    ("Odoo", r"Odoo", False),
]

_COMPILED = [
    (name, re.compile(_B + "(?:" + pat + ")" + _E, 0 if case_sensitive else re.I))
    for name, pat, case_sensitive in TECHNOLOGIES
]


def detect_stack(text):
    """Technology names found in `text`, in the order of the list above, without duplicates."""
    if not text:
        return []
    return [name for name, rx in _COMPILED if rx.search(text)]
