import { z } from "zod";

export const INTAKE_SCHEMA_VERSION = "1.0" as const;
export const SCOPE_PROPOSAL_ARTIFACT_NAME = "scope-proposal" as const;
export const MAX_INTAKE_TEXT_LENGTH = 16 * 1024;
export const MAX_SCOPE_FIELDS = 8;
export const MAX_SCOPE_CHOICES = 8;
export const MAX_INTAKE_ARTIFACT_BYTES = 256 * 1024;
export const MAX_INTAKE_RESPONSE_BYTES = 64 * 1024;

const identifier = z
	.string()
	.trim()
	.min(1)
	.max(128)
	.regex(/^[a-z][a-z0-9_-]*$/u);
const reference = z.string().trim().min(1).max(128);
const intakeText = z.string().trim().min(1).max(MAX_INTAKE_TEXT_LENGTH);
const summaryText = z.string().trim().min(1).max(1024);
const activeContent = /(?:https?|javascript|data):|\{\{|\$\{/iu;
const markup = /<\s*\/?\s*[a-z][^>]*>/iu;

function plainText(
	schema: z.ZodString,
): z.ZodEffects<z.ZodString, string, string> {
	return schema.refine(
		(value) =>
			!activeContent.test(value) &&
			!markup.test(value) &&
			!Array.from(value).some((character) => {
				const codePoint = character.codePointAt(0) ?? 0;
				return (
					codePoint < 32 &&
					character !== "\t" &&
					character !== "\n" &&
					character !== "\r"
				);
			}),
		"Intake display text must not contain markup, URLs, expressions, or control characters.",
	);
}

function normalized(value: string): string {
	return value.trim().split(/\s+/u).join(" ").normalize("NFKC").toLowerCase();
}

function unique(values: string[]): boolean {
	return new Set(values.map(normalized)).size === values.length;
}

const displayText = plainText(intakeText);
const shortSummary = plainText(summaryText);
const fieldDestination = z.enum(["option", "criterion", "constraint"]);
const fieldKind = z.enum([
	"short_text",
	"single_select",
	"multi_select",
	"boolean",
]);

export const ScopeFieldSchema = z
	.object({
		field_id: identifier,
		label: displayText,
		help_text: displayText,
		required: z.boolean(),
		destination: fieldDestination,
		kind: fieldKind,
		choices: z.array(displayText).max(MAX_SCOPE_CHOICES).default([]),
	})
	.strict()
	.superRefine((field, context) => {
		if (!unique(field.choices)) {
			context.addIssue({
				code: z.ZodIssueCode.custom,
				message: "Field choices must be unique.",
			});
		}
		if (
			(field.kind === "single_select" || field.kind === "multi_select") &&
			field.choices.length === 0
		) {
			context.addIssue({
				code: z.ZodIssueCode.custom,
				message: "Select fields require choices.",
			});
		}
		if (
			(field.kind === "short_text" || field.kind === "boolean") &&
			field.choices.length !== 0
		) {
			context.addIssue({
				code: z.ZodIssueCode.custom,
				message: "Short-text and boolean fields cannot define choices.",
			});
		}
		if (field.kind === "boolean" && field.destination === "option") {
			context.addIssue({
				code: z.ZodIssueCode.custom,
				message: "Boolean fields cannot populate research options.",
			});
		}
	});

export const ScopeProposalSchema = z
	.object({
		schema_version: z.literal(INTAKE_SCHEMA_VERSION),
		proposal_id: reference,
		question: intakeText,
		summary: shortSummary,
		fields: z.array(ScopeFieldSchema).min(1).max(MAX_SCOPE_FIELDS),
		suggested_options: z.array(displayText).max(4).default([]),
		suggested_criteria: z.array(displayText).min(1).max(8),
		suggested_constraints: z.array(displayText).max(8).default([]),
		default_depth: z.enum(["fast", "normal", "deep"]).default("normal"),
	})
	.strict()
	.superRefine((proposal, context) => {
		if (!unique(proposal.fields.map((field) => field.field_id))) {
			context.addIssue({
				code: z.ZodIssueCode.custom,
				message: "Scope field IDs must be unique.",
			});
		}
		for (const values of [
			proposal.suggested_options,
			proposal.suggested_criteria,
			proposal.suggested_constraints,
		]) {
			if (!unique(values)) {
				context.addIssue({
					code: z.ZodIssueCode.custom,
					message: "Suggested values must be unique.",
				});
			}
		}

		const optionFields = proposal.fields.filter(
			(field) => field.destination === "option",
		);
		const optionCapacity = optionFields.reduce(
			(total, field) =>
				total + (field.kind === "multi_select" ? field.choices.length : 1),
			proposal.suggested_options.length,
		);
		if (optionCapacity < 2) {
			context.addIssue({
				code: z.ZodIssueCode.custom,
				message: "A scope proposal must make at least two options possible.",
			});
		}
		if (
			proposal.suggested_options.length < 2 &&
			!optionFields.some((field) => field.required)
		) {
			context.addIssue({
				code: z.ZodIssueCode.custom,
				message:
					"Incomplete suggested options require a required option field.",
			});
		}
	});

const artifactProvenanceSchema = z
	.object({
		producer_agent: reference,
		remote_task_id: reference,
		created_at: z.string().datetime({ offset: true }),
	})
	.strict();

export const ScopeProposalArtifactSchema = z
	.object({
		schema_version: z.literal(INTAKE_SCHEMA_VERSION),
		provenance: artifactProvenanceSchema,
		payload: ScopeProposalSchema,
	})
	.strict();

const answer = z.union([
	z.string().trim().min(1).max(MAX_INTAKE_TEXT_LENGTH),
	z
		.array(z.string().trim().min(1).max(MAX_INTAKE_TEXT_LENGTH))
		.max(MAX_SCOPE_CHOICES),
	z.boolean(),
]);

export const IntakeResponseSchema = z
	.object({
		schema_version: z.literal(INTAKE_SCHEMA_VERSION),
		session_id: reference,
		proposal_id: reference,
		proposal_version: z.literal(INTAKE_SCHEMA_VERSION),
		answers: z.record(identifier, answer),
	})
	.strict()
	.superRefine((response, context) => {
		if (Object.keys(response.answers).length > MAX_SCOPE_FIELDS) {
			context.addIssue({
				code: z.ZodIssueCode.custom,
				message: "Too many intake answers.",
			});
		}
		for (const selected of Object.values(response.answers)) {
			if (Array.isArray(selected) && !unique(selected)) {
				context.addIssue({
					code: z.ZodIssueCode.custom,
					message: "Selected values must be unique.",
				});
			}
		}
	});

export type ScopeField = z.infer<typeof ScopeFieldSchema>;
export type ScopeProposal = z.infer<typeof ScopeProposalSchema>;
export type ScopeProposalArtifact = z.infer<typeof ScopeProposalArtifactSchema>;
export type IntakeResponse = z.infer<typeof IntakeResponseSchema>;

export function parseScopeProposalArtifact(
	value: unknown,
): ScopeProposalArtifact {
	requireJsonSize(value, MAX_INTAKE_ARTIFACT_BYTES, "Scope proposal artifact");
	requireVersion(value, "schema_version", "Scope proposal artifact");
	return parse(ScopeProposalArtifactSchema, value, "scope proposal artifact");
}

export function parseIntakeResponse(value: unknown): IntakeResponse {
	requireJsonSize(value, MAX_INTAKE_RESPONSE_BYTES, "Intake response");
	requireVersion(value, "schema_version", "Intake response");
	return parse(IntakeResponseSchema, value, "intake response");
}

export function validateIntakeResponse(
	proposal: ScopeProposal,
	value: unknown,
): IntakeResponse {
	const response = parseIntakeResponse(value);
	if (response.proposal_id !== proposal.proposal_id) {
		throw new Error("Intake response proposal ID does not match the proposal.");
	}
	if (response.proposal_version !== proposal.schema_version) {
		throw new Error(
			"Intake response proposal version is stale or unsupported.",
		);
	}

	const fields = new Map(
		proposal.fields.map((field) => [field.field_id, field]),
	);
	for (const fieldId of Object.keys(response.answers)) {
		if (!fields.has(fieldId)) {
			throw new Error(`Intake response contains unknown field: ${fieldId}`);
		}
	}
	for (const field of proposal.fields) {
		if (field.required && !(field.field_id in response.answers)) {
			throw new Error(
				`Intake response is missing required field: ${field.field_id}`,
			);
		}
	}

	for (const [fieldId, selected] of Object.entries(response.answers)) {
		const field = fields.get(fieldId);
		if (field === undefined) {
			throw new Error(`Intake response contains unknown field: ${fieldId}`);
		}
		if (
			(field.kind === "short_text" || field.kind === "single_select") &&
			typeof selected !== "string"
		) {
			throw new Error(`Field ${fieldId} requires one text value.`);
		}
		if (field.kind === "multi_select" && !Array.isArray(selected)) {
			throw new Error(`Field ${fieldId} requires a list of text values.`);
		}
		if (field.kind === "boolean" && typeof selected !== "boolean") {
			throw new Error(`Field ${fieldId} requires a boolean value.`);
		}
		if (field.required && Array.isArray(selected) && selected.length === 0) {
			throw new Error(`Required field ${fieldId} cannot be empty.`);
		}
		if (field.choices.length > 0) {
			const allowed = new Set(field.choices.map(normalized));
			const values = Array.isArray(selected) ? selected : [selected];
			if (
				values.some(
					(item) => typeof item === "string" && !allowed.has(normalized(item)),
				)
			) {
				throw new Error(
					`Field ${fieldId} contains a value outside its declared choices.`,
				);
			}
		}
	}
	return response;
}

function parse<Schema extends z.ZodTypeAny>(
	schema: Schema,
	value: unknown,
	label: string,
): z.infer<Schema> {
	const result = schema.safeParse(value);
	if (!result.success) {
		const issue = result.error.issues[0];
		const location = issue?.path.join(".");
		throw new Error(
			`Invalid ${label}${location ? ` at ${location}` : ""}: ${issue?.message ?? "unknown"}`,
		);
	}
	return result.data;
}

function requireVersion(value: unknown, key: string, label: string): void {
	if (
		typeof value === "object" &&
		value !== null &&
		(value as Record<string, unknown>)[key] !== INTAKE_SCHEMA_VERSION
	) {
		throw new Error(
			`Unsupported ${label} schema: ${String((value as Record<string, unknown>)[key])}`,
		);
	}
}

function requireJsonSize(value: unknown, maximum: number, label: string): void {
	let encoded: string;
	try {
		encoded = JSON.stringify(value);
	} catch {
		throw new Error(`${label} must be JSON-safe.`);
	}
	if (
		encoded === undefined ||
		new TextEncoder().encode(encoded).byteLength > maximum
	) {
		throw new Error(`${label} exceeds the allowed size.`);
	}
}
