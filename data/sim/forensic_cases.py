# /// script
# dependencies = [
#   "data-designer",
#   "pydantic",
# ]
# ///
import data_designer.config as dd
from pydantic import BaseModel, Field


class ForensicEvidence(BaseModel):
    evidence_id: str = Field(description="Unique evidence ID, e.g. EVD-2024-0042")
    evidence_type: str = Field(description="Type: physical, digital, documentary, biological, or testimonial")
    description: str = Field(description="1-2 sentence description of the evidence item")
    collection_location: str = Field(description="Where the evidence was collected")
    chain_of_custody: str = Field(description="Brief chain of custody note")


class EvidenceList(BaseModel):
    records: list[ForensicEvidence] = Field(description="2 to 4 evidence items for this case")


def load_config_builder() -> dd.DataDesignerConfigBuilder:
    config_builder = dd.DataDesignerConfigBuilder()

    # ── Identifiers ──────────────────────────────────────────────────────────
    config_builder.add_column(dd.SamplerColumnConfig(
        name="case_id",
        sampler_type="uuid",
        params=dd.UUIDSamplerParams(prefix="SC-2024-", short_form=True, uppercase=True),
    ))

    config_builder.add_column(dd.SamplerColumnConfig(
        name="incident_date",
        sampler_type="datetime",
        params=dd.DatetimeSamplerParams(start="2022-01-01", end="2024-12-31", unit="D"),
        convert_to="%Y-%m-%d",
    ))

    # ── Case classification ───────────────────────────────────────────────────
    config_builder.add_column(dd.SamplerColumnConfig(
        name="case_type",
        sampler_type="category",
        params=dd.CategorySamplerParams(values=[
            "drug_trafficking",
            "cybercrime",
            "financial_fraud",
            "robbery",
            "homicide",
            "assault",
            "human_trafficking",
            "money_laundering",
        ]),
    ))

    config_builder.add_column(dd.SamplerColumnConfig(
        name="severity",
        sampler_type="category",
        params=dd.CategorySamplerParams(
            values=["low", "medium", "high", "critical"],
            weights=[1, 3, 3, 1],
        ),
    ))

    config_builder.add_column(dd.SamplerColumnConfig(
        name="district",
        sampler_type="category",
        params=dd.CategorySamplerParams(values=[
            "Bedok", "Tampines", "Jurong East", "Woodlands",
            "Ang Mo Kio", "Clementi", "Bukit Timah", "Geylang",
            "Toa Payoh", "Yishun", "Hougang", "Punggol",
        ]),
    ))

    config_builder.add_column(dd.SamplerColumnConfig(
        name="case_status",
        sampler_type="category",
        params=dd.CategorySamplerParams(
            values=["open", "under_investigation", "pending_trial", "closed"],
            weights=[2, 4, 2, 2],
        ),
    ))

    # ── Suspect nationality (mix of Singaporeans and foreigners) ────────────
    config_builder.add_column(dd.SamplerColumnConfig(
        name="suspect_nationality",
        sampler_type="category",
        params=dd.CategorySamplerParams(
            values=["Singaporean", "Malaysian", "Chinese national", "Indian national",
                    "Vietnamese national", "Filipino", "Indonesian", "British national"],
            weights=[4, 3, 2, 2, 1, 1, 1, 1],
        ),
    ))

    # ── Suspect name — Singapore-context names reflecting nationality mix ────
    config_builder.add_column(dd.SamplerColumnConfig(
        name="suspect_name",
        sampler_type="category",
        params=dd.CategorySamplerParams(values=[
            # Singaporean Chinese
            "Tan Wei Jie", "Lim Hui Ling", "Chen Jia Hao", "Wong Xiu Mei", "Ng Jun Wei",
            "Lee Boon Kiat", "Goh Shu Fen", "Ong Zhi Xian", "Chua Mei Ling", "Teo Kok Siong",
            # Singaporean Malay
            "Muhammad Faiz bin Rosli", "Nur Aisyah binte Hassan", "Ahmad Faris bin Aziz",
            "Siti Nurbaya binte Hamid", "Mohd Hafiz bin Sulaiman",
            # Singaporean Indian
            "Rajesh s/o Subramaniam", "Priya d/o Krishnan", "Arjun s/o Nair",
            "Kavitha d/o Pillai", "Vikram s/o Rajan",
            # Malaysian
            "Chong Kok Wai", "Siti Rahayu binte Omar", "Ravi a/l Murugan",
            # Chinese national
            "Wang Jianlong", "Li Xiaomei", "Zhang Wei",
            # Vietnamese / Filipino / Indonesian
            "Nguyen Van Thanh", "Maria Santos", "Budi Santoso",
            # British
            "James Whitfield",
        ]),
    ))

    config_builder.add_column(dd.SamplerColumnConfig(
        name="suspect_age",
        sampler_type="uniform",
        params=dd.UniformSamplerParams(low=18, high=65),
        convert_to="int",
    ))

    # ── Investigating officer — Singapore police names ────────────────────────
    config_builder.add_column(dd.SamplerColumnConfig(
        name="assigned_officer",
        sampler_type="category",
        params=dd.CategorySamplerParams(values=[
            "Inspector Tan Ah Kow", "Inspector Siti Mariam binte Yusof",
            "Inspector Rajendran s/o Pillai", "Staff Sergeant Lim Chee Keong",
            "Inspector Wong Kok Wah", "Senior Staff Sergeant Faridah binte Ismail",
            "Inspector Goh Eng Seng", "Staff Sergeant Ng Boon Huat",
        ]),
    ))

    # ── LLM-generated narrative columns ──────────────────────────────────────
    config_builder.add_column(dd.LLMTextColumnConfig(
        name="incident_summary",
        model_alias="nvidia-text",
        system_prompt=(
            "You are a Singapore Police Force report writer. "
            "Write formal, factual police incident summaries in British English. "
            "Be concise and use standard police report language. "
            "Reference Singapore-specific locations, MRT stations, hawker centres, HDB blocks, "
            "or local context where relevant. "
            "Do not include case IDs or dates — those are added separately."
        ),
        prompt=(
            "Write a 3-5 sentence incident summary for a {{ case_type | replace('_', ' ') }} case "
            "in the {{ district }} district of Singapore. "
            "The suspect is {{ suspect_name }} ({{ suspect_nationality }}), aged {{ suspect_age }}. "
            "Severity: {{ severity }}. "
            "Include specific Singapore-context details (e.g. HDB blocks, coffeeshops, MRT, "
            "local businesses) and circumstances of discovery."
        ),
    ))

    config_builder.add_column(dd.LLMStructuredColumnConfig(
        name="evidence",
        model_alias="nvidia-text",
        output_format=EvidenceList,
        system_prompt=(
            "You are a forensic evidence cataloguer for the Singapore Police Force. "
            "Generate realistic, specific evidence items for criminal cases. "
            "Evidence IDs must follow the format EVD-YYYY-NNNN."
        ),
        prompt=(
            "Generate a list of 2-4 forensic evidence items for case type: {{ case_type | replace('_', ' ') }}. "
            "The incident occurred in {{ district }}, Singapore on {{ incident_date }}. "
            "Incident context: {{ incident_summary }}"
        ),
    ))

    config_builder.add_column(dd.LLMTextColumnConfig(
        name="lab_report",
        model_alias="nvidia-text",
        system_prompt=(
            "You are a Singapore Police Force forensic scientist writing formal laboratory reports. "
            "Use technical but clear language. Reports should be 3-6 sentences."
        ),
        prompt=(
            "Write a forensic laboratory analysis report for the following evidence items "
            "from a {{ case_type | replace('_', ' ') }} case:\n"
            "{% for item in evidence.records %}"
            "- {{ item.evidence_id }}: {{ item.description }}\n"
            "{% endfor %}"
            "State findings, analytical methods used, and conclusions relevant to the case."
        ),
    ))

    config_builder.add_column(dd.LLMTextColumnConfig(
        name="witness_statement",
        model_alias="nvidia-text",
        system_prompt=(
            "You are transcribing a witness statement for the Singapore Police Force. "
            "Write in first person as the witness. Use natural Singapore English — "
            "the witness may mix in occasional Singlish expressions like 'lah', 'leh', 'lor', "
            "'can', 'confirm', 'aiyah', or reference local places naturally. "
            "Keep it realistic, 3-5 sentences."
        ),
        prompt=(
            "Write a witness statement for a {{ case_type | replace('_', ' ') }} incident "
            "in {{ district }}, Singapore on {{ incident_date }}. "
            "Context: {{ incident_summary }}"
        ),
    ))

    config_builder.add_column(dd.LLMTextColumnConfig(
        name="whatsapp_chat",
        model_alias="nvidia-text",
        system_prompt=(
            "You are generating a realistic WhatsApp chat transcript extracted from a suspect's phone "
            "by Singapore Police Force investigators. "
            "Format: each line is '[HH:MM] Name: message'. "
            "Messages should be in Singapore English — mix of English, Singlish, and occasional "
            "Mandarin/Malay words (romanised). Use abbreviations typical of WhatsApp (lol, ok, ya, nvm, etc). "
            "The chat should contain incriminating or suspicious content relevant to the case type, "
            "but written naturally as if the participants don't know they're being watched. "
            "Generate 8-15 chat messages spanning a short time window."
        ),
        prompt=(
            "Generate a WhatsApp chat transcript from the phone of {{ suspect_name }} "
            "({{ suspect_nationality }}) related to a {{ case_type | replace('_', ' ') }} case "
            "in {{ district }}, Singapore. "
            "Incident context: {{ incident_summary }}"
        ),
    ))

    config_builder.add_column(dd.LLMTextColumnConfig(
        name="investigating_officer_notes",
        model_alias="nvidia-text",
        system_prompt=(
            "You are {{ assigned_officer }}, writing internal investigation notes "
            "for the Singapore Police Force. Be concise and factual. 2-4 sentences."
        ),
        prompt=(
            "Write investigating officer notes for case {{ case_id }} ({{ case_type | replace('_', ' ') }}). "
            "Status: {{ case_status | replace('_', ' ') }}. "
            "Suspect: {{ suspect_name }}, {{ suspect_nationality }}, aged {{ suspect_age }}. "
            "Summary: {{ incident_summary }} "
            "Evidence collected: {% for item in evidence.records %}{{ item.evidence_id }}{% if not loop.last %}, {% endif %}{% endfor %}. "
            "Note next investigative steps, any ICA/MOM checks needed for foreign suspects, or case disposition."
        ),
    ))

    return config_builder
