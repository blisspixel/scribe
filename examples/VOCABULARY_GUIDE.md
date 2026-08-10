# Custom Vocabulary Quick Reference

## What is Custom Vocabulary?

Custom vocabulary helps Whisper recognize domain-specific terms, proper nouns, and technical jargon more accurately during transcription.

## How It Works

The vocabulary is passed to Whisper as an "initial prompt" that guides the model to recognize these specific terms. This works with both local GPU and OpenAI API transcription.

## File Formats

### Plain Text (.txt)
- One term per line
- Lines starting with # are comments (ignored)
- Blank lines are ignored
- Simple and easy to edit

**Example:**
```
# Cloud Services
Kubernetes
PostgreSQL
AWS Lambda

# Company Terms
Example Company
Example Project
```

### JSON (.json)
- Array of strings
- No comments supported
- Good for programmatic generation

**Example:**
```json
[
  "Kubernetes",
  "PostgreSQL",
  "AWS Lambda",
  "Example Company",
  "Example Project"
]
```

## Usage

### Single File
```bash
scribe transcribe meeting.mp4 --vocabulary my-terms.txt
```

### Batch Processing
```bash
scribe batch *.mp4 --vocabulary tech-terms.txt
```

### With Other Options
```bash
scribe transcribe meeting.mp4 \
  --vocabulary company-terms.txt \
  --method local \
  --language en \
  --no-meme
```

## Best Practices

### 1. Include Proper Nouns
- Company names: "Example Company", "Sample Organization"
- Product names: "Example Product", "Sample Service"
- People's names: "Avery Example", "Jordan Example"
- Team names: "Platform Team", "DevOps Squad"

### 2. Add Technical Terms
- Frameworks: "Kubernetes", "React", "Django"
- Services: "AWS Lambda", "Cloud Functions"
- APIs: "GraphQL", "REST API", "gRPC"
- Tools: "Jenkins", "Terraform", "Docker"

### 3. Use Correct Capitalization
Whisper respects the capitalization you provide:
- "PostgreSQL" (not "postgresql")
- "JavaScript" (not "javascript")
- "OAuth" (not "oauth")

### 4. Include Acronyms
- "API", "REST", "CRUD"
- "CI/CD", "DevOps", "SRE"
- "JWT", "OAuth", "SAML"

### 5. Keep It Focused
- Only include terms likely to appear in your recordings
- Start with 20-50 terms, expand as needed
- Too many terms can reduce effectiveness

### 6. Organize with Comments (txt only)
```
# Infrastructure
Kubernetes
Docker
Terraform

# Databases
PostgreSQL
MongoDB
Redis

# Company Specific
Example Company
Example Project
```

## File Naming

Custom vocabulary files are automatically ignored by git (except examples). Recommended names:

- `vocabulary.txt` - Main vocabulary
- `tech-vocabulary.txt` - Technical terms
- `company-vocabulary.txt` - Company-specific terms
- `project-vocabulary.txt` - Project-specific terms
- `my-vocabulary.txt` - Personal vocabulary

All these patterns are in .gitignore, so your custom terms stay private.

## Testing Your Vocabulary

1. Create a small test file with 5-10 terms
2. Transcribe a short recording that uses those terms
3. Check if the terms are recognized correctly
4. Add more terms as needed

## Common Use Cases

### Software Development
```
Kubernetes
PostgreSQL
GraphQL
TypeScript
React
Jenkins
GitHub Actions
Terraform
```

### Medical/Healthcare
```
Electrocardiogram
Hypertension
Metformin
Hemoglobin A1C
Echocardiogram
```

### Legal
```
Plaintiff
Defendant
Deposition
Subpoena
Voir Dire
Affidavit
```

### Finance
```
Amortization
Depreciation
EBITDA
Liquidity
Portfolio
Diversification
```

### Marketing
```
SEO
SEM
Google Analytics
HubSpot
Mailchimp
ROI
KPI
Conversion Rate
```

## Limitations

- Vocabulary improves accuracy but doesn't guarantee perfect recognition
- Very long vocabulary lists (100+ terms) may be less effective
- Works best with proper nouns and technical terms
- Cannot fix fundamental audio quality issues

## Tips

1. **Start small**: Begin with your most important terms
2. **Test iteratively**: Add terms based on actual transcription errors
3. **Use both formats**: txt for manual editing, json for automation
4. **Share with team**: Keep a team vocabulary file in your project
5. **Update regularly**: Add new terms as your domain evolves
