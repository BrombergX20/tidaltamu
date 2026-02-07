# -----------------------------
# Imports
# -----------------------------

import google.genai as genai
import subprocess
from pathlib import Path

# -----------------------------
# Configuration
# -----------------------------
API_KEY = "AIzaSyCl51AzMOESVxjANj28ewfA4RdBsvIoMug" # Replace this string with your api key
RESUME_TEXT_FILE = "ResumeText"  # plain text resume input in LaTeX format
OUTPUT_TEX = "resume.tex" # outputs the LaTeX format
OUTPUT_PDF = "resume.pdf" # Converts resume.tex into proper Resume format
MODEL_NAME = "gemini-2.5-flash" # You can replace this with any of the other models available


# -----------------------------
# Initialize client info to use LLM in code
# -----------------------------
client = genai.Client(api_key=API_KEY)

# Can uncomment this part if you want to use a different model
# for model in client.models.list():
#     print(model.name)

# -----------------------------
# Read in Resume text in LaTeX format
# -----------------------------
resume_text = Path(RESUME_TEXT_FILE).read_text(encoding="utf-8")

# -----------------------------
# Input job description at this step
# -----------------------------
print("Enter Job Description (type END on its own line):")
job_description = []
while True:
    line = input()
    if line.strip().upper() == "END":
        break
    job_description.append(line)

job_description = " ".join(job_description)

# -----------------------------
# Prompt for LLM, can mix and match which instructions you want to use here
# -----------------------------
# RULES:
# - Use ONLY standard LaTeX (article class)
# - Do NOT define custom commands or environments
# - Do NOT create macros
# - Do NOT use fancy templates
# - Use simple \\section* and \\itemize only
# - Use US Letter paper
# - Use simple margins (0.75in)
# - Do not use raggedright
# - Do not use custom fonts
# - Do not center anything except the name header
# - Output ONLY valid LaTeX
# - No explanations
# - No markdown
# - Do not use \\url or monospace formatting for contact info.
prompt = f"""
You are generating a resume in LaTeX.



TASK:
Recreate the provided resume text as closely as possible in content and layout.
2 pages max allowed.
Optimize bullet wording for the job description.

RESUME TEXT:
{resume_text}

JOB DESCRIPTION:
{job_description}
"""

# -----------------------------
# Generate revised Resume in LaTeX syntax
# -----------------------------
response = client.models.generate_content(
    model=MODEL_NAME,
    contents=[prompt],
)

text = response.text

# Checks if document is in proper format, throws error if \\documentclass is not found
start = text.find("\\documentclass")
if start == -1:
    raise ValueError("Model did not return LaTeX")

latex_code = text[start:].strip()

end = latex_code.find("\\end{document}")
if end != -1:
    latex_code = latex_code[:end + len("\\end{document}")]

# -----------------------------
# Writes the revised Resume text in a .tex file
# -----------------------------
Path(OUTPUT_TEX).write_text(latex_code, encoding="utf-8")
print("LaTeX generated: resume.tex")

# -----------------------------
# Compile and run MiKTeX automatically
# -----------------------------
subprocess.run(
    ["pdflatex", "-interaction=nonstopmode", OUTPUT_TEX],
    check=True
)

print("Final PDF generated: resume.pdf")