"""
Static website content for Ofstride — extracted from JSX source files.

This module provides the knowledge base for the chatbot. Because the website
is a React SPA (JavaScript-rendered), a standard HTTP crawler cannot extract
content. Instead, content is maintained here as structured Python data and
seeded into Qdrant via the /api/crawl endpoint.

Update this file whenever new pages or services are added to the website.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class StaticDocument:
    title: str
    url: str
    section: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ─── Company Overview ────────────────────────────────────────────────────────

COMPANY_OVERVIEW = StaticDocument(
    title="About Ofstride Services LLP",
    url="https://ofstride.com/about",
    section="about",
    content="""
Ofstride Services LLP is a multidisciplinary business consulting firm established in 2019,
providing integrated solutions in Human Resources, Finance, Legal, IT, Business Strategy,
Artificial Intelligence, and Workforce Development.

Ofstride combines defence discipline, corporate leadership, and intelligent systems to deliver
practical, measurable outcomes for businesses across India.

Offices: New Delhi and Bengaluru. Pan-India coverage.
Year established: 2019.
Combined leadership experience: 32+ years.
Integrated services: 10.

Contact: contact@ofstride.com
Book a free 30-minute discovery call at cal.id/ofstride
We respond to all inquiries within 24 hours.
""".strip(),
)

# ─── Team / Consultants ───────────────────────────────────────────────────────

TEAM_PROFILES: list[StaticDocument] = [
    StaticDocument(
        title="Raj Kumar Jha — Managing Partner, People & Workforce",
        url="https://ofstride.com/about",
        section="team",
        content="""
Name: Raj Kumar Jha
Role: Managing Partner
Location: Bangalore
Domain: People & Workforce, HR, Business Administration

Background: Air Veteran with over 32 years of combined defence and corporate leadership experience.
Led HR, operations, administration, and business development across healthcare, hospitality,
insurance, and fitness industries.

Credentials: PG Business Administration, IIMS Kolkata | Business Strategy, IIM Lucknow.

Expertise: HR strategy, workforce planning, talent management, organisational development,
operations management, business administration.

Availability: On request. Contact: contact@ofstride.com
""".strip(),
        metadata={"consultant_name": "Raj Kumar Jha", "role": "Managing Partner", "location": "Bangalore",
                   "domain": "People & Workforce", "source_type": "consultant_profile"},
    ),
    StaticDocument(
        title="Yuvraj Singh — AI & Data Science Consultant",
        url="https://ofstride.com/about",
        section="team",
        content="""
Name: Yuvraj Singh
Role: AI & Data Science Consultant
Location: Bangalore
Domain: Technology & Growth, AI, Data Science

Background: Specialist in Artificial Intelligence, Data Science, and Agentic AI workflows.
Architects intelligent business solutions, predictive analytics, automation frameworks,
and enterprise AI systems.

Credentials: AI Strategy & Implementation | Predictive Analytics | Agentic AI.

Expertise: AI agent development, machine learning, predictive analytics, natural language processing,
data science consulting, digital transformation, IT consulting.

Availability: On request. Contact: contact@ofstride.com
""".strip(),
        metadata={"consultant_name": "Yuvraj Singh", "role": "AI & Data Science Consultant",
                   "location": "Bangalore", "domain": "Technology & Growth", "source_type": "consultant_profile"},
    ),
    StaticDocument(
        title="Naveen Kumar — Senior Consultant, Business Strategy",
        url="https://ofstride.com/about",
        section="team",
        content="""
Name: Naveen Kumar
Role: Senior Consultant — Business Strategy
Location: Noida
Domain: Technology & Growth, Business Strategy

Background: IIT (BHU) Varanasi graduate and founder of Aquvio. Innovation leader with Indian
and UK patents in water purification technology. Recognised with national and international
innovation awards.

Credentials: IIT (BHU) Varanasi | Patented Innovator | National & International Awards.

Expertise: Business strategy, process improvement, innovation consulting, product development,
market intelligence, startup advisory.

Availability: On request. Contact: contact@ofstride.com
""".strip(),
        metadata={"consultant_name": "Naveen Kumar", "role": "Senior Consultant — Business Strategy",
                   "location": "Noida", "domain": "Technology & Growth", "source_type": "consultant_profile"},
    ),
    StaticDocument(
        title="Senthil Kumar Varadarajan — Senior Consultant, IT & Innovation",
        url="https://ofstride.com/about",
        section="team",
        content="""
Name: Senthil Kumar Varadarajan
Role: Senior Consultant — IT & Innovation
Location: Bangalore
Domain: Technology & Growth, IT

Background: Over 25 years of cross-industry experience. Specialises in digital transformation,
managed IT services, analytics, enterprise technology, and innovation consulting.
Industries: Aviation, Healthcare, Manufacturing, Logistics, Retail.

Credentials: 25+ Years Cross-Industry Experience.

Expertise: IT consulting, digital transformation, managed IT services, enterprise technology,
cloud infrastructure, system integration, analytics.

Availability: On request. Contact: contact@ofstride.com
""".strip(),
        metadata={"consultant_name": "Senthil Kumar Varadarajan", "role": "Senior Consultant — IT & Innovation",
                   "location": "Bangalore", "domain": "Technology & Growth", "source_type": "consultant_profile"},
    ),
    StaticDocument(
        title="Girindra Kumar Pathak — Senior Consultant, Legal Services",
        url="https://ofstride.com/about",
        section="team",
        content="""
Name: Girindra Kumar Pathak
Role: Senior Consultant — Legal Services
Location: Delhi
Domain: Finance & Compliance, Legal

Background: Former Indian Air Force veteran and practicing advocate with more than 15 years of
legal experience. Specialises in labour law, industrial disputes, civil litigation, arbitration,
family law, and corporate legal advisory.

Credentials: Ex-IAF | 15+ Years Legal Practice | Labour & Corporate Law Expert.

Expertise: Labour law, industrial disputes, civil litigation, arbitration, family law,
corporate legal advisory, compliance, regulatory matters, Delhi High Court.

Availability: On request. Contact: contact@ofstride.com
""".strip(),
        metadata={"consultant_name": "Girindra Kumar Pathak", "role": "Senior Consultant — Legal Services",
                   "location": "Delhi", "domain": "Finance & Compliance", "source_type": "consultant_profile"},
    ),
    StaticDocument(
        title="Sunder Prakash Burkoti — Senior Consultant, Finance & Taxation",
        url="https://ofstride.com/about",
        section="team",
        content="""
Name: Sunder Prakash Burkoti
Role: Senior Consultant — Finance & Taxation
Location: Delhi
Domain: Finance & Compliance

Background: Practicing Cost & Management Accountant (CMA) with extensive expertise in finance,
taxation, cost management, and regulatory compliance. Helps organizations strengthen financial
governance and optimise costs.

Credentials: CMA | Financial Planning | Cost Accounting | Taxation & Audit.

Expertise: Financial advisory, taxation, GST, cost management, regulatory compliance,
audit, financial planning, virtual CFO services.

Availability: On request. Contact: contact@ofstride.com
""".strip(),
        metadata={"consultant_name": "Sunder Prakash Burkoti", "role": "Senior Consultant — Finance & Taxation",
                   "location": "Delhi", "domain": "Finance & Compliance", "source_type": "consultant_profile"},
    ),
]

# ─── Services ─────────────────────────────────────────────────────────────────

SERVICES: list[StaticDocument] = [
    StaticDocument(
        title="Human Resource Consulting",
        url="https://ofstride.com/services/human-resource-consulting",
        section="services",
        content="""
Service: Human Resource Consulting
Tagline: HR That Predicts. Not Just Reacts.
Category: People & Workforce

Description: AI-driven workforce strategy, org design, and culture building built for teams that scale.

Features:
- Predictive attrition modelling
- Automated skill-gap analysis
- AI-assisted policy drafting
- Intelligent org-structure recommendations

Use cases: Workforce strategy, organisational design, culture transformation, attrition management,
employee engagement, HR operations.
""".strip(),
    ),
    StaticDocument(
        title="Executive Search & Recruitment",
        url="https://ofstride.com/services/executive-search-recruitment",
        section="services",
        content="""
Service: Executive Search & Recruitment
Tagline: Find Leaders Before Your Competitors Do.
Category: People & Workforce

Description: AI-powered talent intelligence across India. The right person, the right role, the right time.

Features:
- AI-candidate matching
- Automated resume parsing
- Predictive cultural-fit analysis
- Intelligent interview scheduling

Use cases: C-suite hiring, leadership roles, specialist talent acquisition, campus recruitment.
""".strip(),
    ),
    StaticDocument(
        title="Payroll & HR Compliance",
        url="https://ofstride.com/services/payroll-hr-compliance",
        section="services",
        content="""
Service: Payroll & HR Compliance
Tagline: Compliance on Autopilot.
Category: People & Workforce

Description: Zero-error payroll, real-time statutory monitoring, and AI-generated filings across every state.

Features:
- Automated payroll with anomaly detection
- Real-time compliance monitoring
- AI-generated PF/ESI/PT filings
- Predictive audit-risk alerts

Use cases: Monthly payroll, PF/ESI/PT compliance, multi-state statutory compliance, audit readiness.
""".strip(),
    ),
    StaticDocument(
        title="Financial Consulting & Virtual CFO",
        url="https://ofstride.com/services/financial-consulting-virtual-cfo",
        section="services",
        content="""
Service: Financial Consulting & Virtual CFO
Tagline: CFO Clarity. Without the Full-Time Cost.
Category: Finance & Compliance

Description: AI-enhanced forecasting, cash-flow intelligence, and investor-ready financial discipline.

Features:
- Automated financial forecasting
- AI-driven cash-flow optimisation
- Intelligent MIS dashboards
- Predictive fundraising readiness

Use cases: Virtual CFO services, financial planning, investor reporting, cash flow management,
fundraising readiness, financial governance.
""".strip(),
    ),
    StaticDocument(
        title="GST & Tax Advisory",
        url="https://ofstride.com/services/gst-tax-advisory",
        section="services",
        content="""
Service: GST & Tax Advisory
Tagline: Tax Strategy That Stays Ahead.
Category: Finance & Compliance

Description: AI tracks every regulatory change so you can focus on growth while we handle complexity.

Features:
- Automated GST reconciliation
- AI-powered tax-saving recommendations
- Predictive litigation-risk scoring
- Smart filing calendars

Use cases: GST registration, GST returns, GST reconciliation, income tax advisory, tax planning,
litigation support, regulatory compliance.
""".strip(),
    ),
    StaticDocument(
        title="Legal & Regulatory Compliance",
        url="https://ofstride.com/services/legal-regulatory-compliance",
        section="services",
        content="""
Service: Legal & Regulatory Compliance
Tagline: Legal Protection, 24/7.
Category: Finance & Compliance

Description: AI-monitored compliance, smart contract review, and proactive risk flagging
across labour, corporate, and civil law.

Features:
- AI-powered contract review
- Automated regulatory alerts
- Intelligent case-law research
- Smart document drafting

Use cases: Labour law advisory, contract review, corporate compliance, civil litigation,
arbitration, regulatory advisory, legal risk management.
""".strip(),
    ),
    StaticDocument(
        title="IT Consulting & Digital Transformation",
        url="https://ofstride.com/services/it-consulting-digital-transformation",
        section="services",
        content="""
Service: IT Consulting & Digital Transformation
Tagline: Technology That Learns With You.
Category: Technology & Growth

Description: Cloud, automation, and AI-integrated systems that adapt as your business grows.

Features:
- AI-driven infrastructure optimisation
- Automated system monitoring
- Intelligent cloud cost management
- Smart workflow automation

Use cases: IT strategy, cloud migration, system integration, infrastructure optimisation,
workflow automation, enterprise technology advisory.
""".strip(),
    ),
    StaticDocument(
        title="AI & Data Science Consulting",
        url="https://ofstride.com/services/ai-data-science-consulting",
        section="services",
        content="""
Service: AI & Data Science Consulting
Tagline: Build Systems That Think.
Category: Technology & Growth

Description: Custom AI agents, predictive models, and automation frameworks.
We do not just advise — we architect intelligence.

Features:
- Custom AI agent development
- Predictive analytics models
- Natural language processing
- Self-improving ML systems

Use cases: AI strategy, machine learning model development, NLP solutions, automation,
data analytics, AI-powered dashboards, agentic workflows.
""".strip(),
    ),
    StaticDocument(
        title="Business Strategy & Process Improvement",
        url="https://ofstride.com/services/business-strategy-process-improvement",
        section="services",
        content="""
Service: Business Strategy & Process Improvement
Tagline: Strategy That Executes Itself.
Category: Technology & Growth

Description: AI-powered market intelligence, process optimisation, and scenario planning.
Your roadmap, continuously updated.

Features:
- AI-powered market intelligence
- Automated process mapping
- Predictive performance dashboards
- Intelligent scenario planning

Use cases: Business strategy, market analysis, process improvement, performance management,
growth planning, operational excellence, startup advisory.
""".strip(),
    ),
    StaticDocument(
        title="Employer of Record (EOR) & Workforce Solutions",
        url="https://ofstride.com/services/employer-of-record-workforce",
        section="services",
        content="""
Service: Employer of Record (EOR) & Workforce Solutions
Tagline: Hire Anywhere. Comply Everywhere.
Category: People & Workforce

Description: Pan-India workforce expansion with AI-driven onboarding, compliance,
and contractor management.

Features:
- Automated multi-state compliance
- AI-driven contractor classification
- Intelligent onboarding workflows
- Predictive workforce planning

Use cases: EOR services, pan-India hiring, contractor management, remote workforce,
multi-state compliance, workforce expansion.
""".strip(),
    ),
]

# ─── Industries ───────────────────────────────────────────────────────────────

INDUSTRIES = StaticDocument(
    title="Industries Served by Ofstride",
    url="https://ofstride.com/industries",
    section="industries",
    content="""
Ofstride provides consulting services across the following industries:

Manufacturing: AI-driven supply chain optimisation, workforce planning, and compliance management.
Engineering: Talent acquisition, project cost management, and digital transformation.
Healthcare: Regulatory compliance, workforce management, and AI-powered patient analytics.
Hospitality: Staffing solutions, financial controls, and operational excellence for hotels and restaurants.
Retail: Demand forecasting, workforce scaling, and digital transformation for retail chains and e-commerce.
Insurance: Risk analytics, regulatory compliance, and AI-driven claims processing optimisation.
Pharmaceuticals: Quality compliance, R&D tax incentives, and supply chain intelligence.
Technology: AI strategy, talent acquisition, and scalable infrastructure for tech startups and enterprises.
Logistics: Route optimisation, workforce management, and compliance across multi-state operations.
Education: Institutional compliance, financial governance, and digital learning infrastructure.
Wellness & Fitness: Membership analytics, staff management, and growth strategy.
Startups: End-to-end support from incorporation to scaling — HR, finance, legal, and AI strategy.
MSMEs: Affordable, scalable consulting across all service lines for small and medium enterprises.
""".strip(),
)

# ─── Contact & Engagement ─────────────────────────────────────────────────────

CONTACT_INFO = StaticDocument(
    title="Contact Ofstride — Get in Touch",
    url="https://ofstride.com/contact",
    section="contact",
    content="""
Contact Ofstride Services LLP:

Email: contact@ofstride.com
Offices: New Delhi and Bengaluru, with pan-India coverage.
Response time: All inquiries answered within 24 hours.

Ways to get in touch:
1. Book a FREE 30-minute discovery call: cal.id/ofstride (also available at ofstride.com/book-call)
2. Send a message via the contact form at ofstride.com/contact
3. Email directly: contact@ofstride.com

For consultant recommendations, service inquiries, or to discuss a business requirement,
book a discovery call or send an email. An Ofstride advisor will respond within 24 hours.
""".strip(),
)


def get_all_documents() -> list[StaticDocument]:
    """Return all static content documents."""
    docs: list[StaticDocument] = [COMPANY_OVERVIEW, CONTACT_INFO, INDUSTRIES]
    docs.extend(TEAM_PROFILES)
    docs.extend(SERVICES)
    return docs
