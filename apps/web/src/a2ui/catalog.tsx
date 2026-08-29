import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useId,
  useState,
} from "react";
import {
  createBinderlessComponentImplementation,
  type ReactComponentImplementation,
} from "@a2ui/react/v0_9";
import { Catalog, type ComponentContext } from "@a2ui/web_core/v0_9";
import {
  ButtonApi,
  CheckBoxApi,
  ChoicePickerApi,
  ColumnApi,
  RowApi,
  TextApi,
  TextFieldApi,
} from "@a2ui/web_core/v0_9/basic_catalog";

import { A2UI_CATALOG_ID } from "./contracts";

export const AGENTDESK_A2UI_COMPONENTS = [
  "Text",
  "TextField",
  "ChoicePicker",
  "CheckBox",
  "Column",
  "Row",
  "Button",
] as const;

type RenderState = {
  busy: boolean;
  errors: Readonly<Record<string, string>>;
  requiredFieldIds: ReadonlySet<string>;
};

const IntakeRenderContext = createContext<RenderState>({
  busy: false,
  errors: {},
  requiredFieldIds: new Set(),
});

export function IntakeRenderProvider({
  busy,
  children,
  errors,
  requiredFieldIds,
}: {
  busy: boolean;
  children: ReactNode;
  errors: Readonly<Record<string, string>>;
  requiredFieldIds: string[];
}) {
  return (
    <IntakeRenderContext.Provider
      value={{ busy, errors, requiredFieldIds: new Set(requiredFieldIds) }}
    >
      {children}
    </IntakeRenderContext.Provider>
  );
}

const TrustedText = createBinderlessComponentImplementation(TextApi, ({ context }) => {
  const props = rawProps(context);
  const value = literalText(props.text);
  if (props.variant === "h2") return <h3 className="a2ui-intake__title">{value}</h3>;
  if (props.variant === "caption") return <p className="a2ui-intake__help">{value}</p>;
  return <p className="a2ui-intake__text">{value}</p>;
});

const TrustedTextField = createBinderlessComponentImplementation(TextFieldApi, ({ context }) => {
  const id = useId();
  const props = rawProps(context);
  const fieldId = fieldIdFromComponent(context.componentModel.id);
  const renderState = useContext(IntakeRenderContext);
  const [value, setValue] = useBoundAnswer<string>(context, "");
  const description = accessibility(props).description;
  const descriptionId = `${id}-description`;
  const errorId = `${id}-error`;
  const error = renderState.errors[fieldId];
  const required = renderState.requiredFieldIds.has(fieldId);
  return (
    <div className="a2ui-intake__field" data-field-id={fieldId}>
      <label htmlFor={id}>{literalText(props.label)}</label>
      {description && <span id={descriptionId} className="a2ui-intake__description">{description}</span>}
      <input
        aria-describedby={[description ? descriptionId : "", error ? errorId : ""].filter(Boolean).join(" ") || undefined}
        aria-invalid={error ? true : undefined}
        aria-required={required}
        disabled={renderState.busy}
        id={id}
        name={fieldId}
        onChange={(event) => setValue(event.target.value)}
        required={required}
        type="text"
        value={value}
      />
      {error && <span id={errorId} className="a2ui-intake__error">{error}</span>}
    </div>
  );
});

const TrustedChoicePicker = createBinderlessComponentImplementation(ChoicePickerApi, ({ context }) => {
  const id = useId();
  const props = rawProps(context);
  const fieldId = fieldIdFromComponent(context.componentModel.id);
  const renderState = useContext(IntakeRenderContext);
  const [selected, setSelected] = useBoundAnswer<string[]>(context, []);
  const multiple = props.variant === "multipleSelection";
  const description = accessibility(props).description;
  const descriptionId = `${id}-description`;
  const errorId = `${id}-error`;
  const error = renderState.errors[fieldId];
  const required = renderState.requiredFieldIds.has(fieldId);
  return (
    <fieldset
      aria-describedby={[description ? descriptionId : "", error ? errorId : ""].filter(Boolean).join(" ") || undefined}
      aria-invalid={error ? true : undefined}
      className="a2ui-intake__field"
      data-field-id={fieldId}
    >
      <legend>{literalText(props.label)}</legend>
      {description && <span id={descriptionId} className="a2ui-intake__description">{description}</span>}
      <div className="a2ui-intake__choices">
        {choiceOptions(props).map((option) => {
          const checked = selected.includes(option.value);
          return (
            <label key={option.value}>
              <input
                checked={checked}
                disabled={renderState.busy}
                name={fieldId}
                onChange={() => setSelected(multiple ? checked ? selected.filter((value) => value !== option.value) : [...selected, option.value] : [option.value])}
                type={multiple ? "checkbox" : "radio"}
                required={required}
                value={option.value}
              />
              <span>{option.label}</span>
            </label>
          );
        })}
      </div>
      {error && <span id={errorId} className="a2ui-intake__error">{error}</span>}
    </fieldset>
  );
});

const TrustedCheckBox = createBinderlessComponentImplementation(CheckBoxApi, ({ context }) => {
  const id = useId();
  const props = rawProps(context);
  const fieldId = fieldIdFromComponent(context.componentModel.id);
  const renderState = useContext(IntakeRenderContext);
  const [checked, setChecked] = useBoundAnswer<boolean>(context, false);
  const description = accessibility(props).description;
  const descriptionId = `${id}-description`;
  return (
    <div className="a2ui-intake__field a2ui-intake__checkbox" data-field-id={fieldId}>
      <label htmlFor={id}>
        <input
          aria-describedby={description ? descriptionId : undefined}
          checked={checked}
          disabled={renderState.busy}
          id={id}
          name={fieldId}
          onChange={(event) => setChecked(event.target.checked)}
          type="checkbox"
        />
        <span>{literalText(props.label)}</span>
      </label>
      {description && <span id={descriptionId} className="a2ui-intake__description">{description}</span>}
    </div>
  );
});

const TrustedColumn = createBinderlessComponentImplementation(ColumnApi, ({ buildChild, context }) => (
  <div className="a2ui-intake__column">
    {children(rawProps(context)).map((id) => <div key={id}>{buildChild(id)}</div>)}
  </div>
));

const TrustedRow = createBinderlessComponentImplementation(RowApi, ({ buildChild, context }) => (
  <div className="a2ui-intake__actions">
    {children(rawProps(context)).map((id) => <div key={id}>{buildChild(id)}</div>)}
  </div>
));

const TrustedButton = createBinderlessComponentImplementation(ButtonApi, ({ buildChild, context }) => {
  const props = rawProps(context);
  const { busy } = useContext(IntakeRenderContext);
  const child = literalText(props.child);
  const dispatch = () => {
    const action = props.action;
    if (typeof action !== "object" || action === null) return;
    void context.dispatchAction(context.dataContext.resolveAction(action as never));
  };
  return (
    <button
      aria-label={accessibility(props).label || undefined}
      className={`a2ui-intake__button a2ui-intake__button--${literalText(props.variant)}`}
      disabled={busy}
      onClick={dispatch}
      type="button"
    >
      {child ? buildChild(child) : null}
    </button>
  );
});

const implementations: ReactComponentImplementation[] = [
  TrustedText,
  TrustedTextField,
  TrustedChoicePicker,
  TrustedCheckBox,
  TrustedColumn,
  TrustedRow,
  TrustedButton,
];

export const agentDeskA2uiCatalog = new Catalog(A2UI_CATALOG_ID, implementations);

function useBoundAnswer<Value>(context: ComponentContext, fallback: Value): [Value, (value: Value) => void] {
  const binding = rawProps(context).value;
  const path = typeof binding === "object" && binding !== null && "path" in binding && typeof binding.path === "string"
    ? binding.path
    : "";
  const [value, setLocalValue] = useState<Value>(() => {
    const value = path ? context.dataContext.dataModel.get(path) : undefined;
    return (value === undefined ? fallback : value) as Value;
  });
  const setValue = useCallback((next: Value) => {
    context.dataContext.set(path, next);
    setLocalValue(next);
  }, [context, path]);
  return [value, setValue];
}

function rawProps(context: ComponentContext): Record<string, unknown> {
  return context.componentModel.properties;
}

function accessibility(props: Record<string, unknown>): { label: string; description: string } {
  const value = props.accessibility;
  if (typeof value !== "object" || value === null) return { label: "", description: "" };
  const record = value as Record<string, unknown>;
  return { label: literalText(record.label), description: literalText(record.description) };
}

function choiceOptions(props: Record<string, unknown>): Array<{ label: string; value: string }> {
  return Array.isArray(props.options)
    ? props.options.flatMap((option) => {
        if (typeof option !== "object" || option === null) return [];
        const record = option as Record<string, unknown>;
        const label = literalText(record.label);
        const value = literalText(record.value);
        return label && value ? [{ label, value }] : [];
      })
    : [];
}

function children(props: Record<string, unknown>): string[] {
  return Array.isArray(props.children)
    ? props.children.filter((value): value is string => typeof value === "string")
    : [];
}

function fieldIdFromComponent(componentId: string): string {
  return componentId.startsWith("field-") ? componentId.slice("field-".length) : componentId;
}

function literalText(value: unknown): string {
  return typeof value === "string" ? value : "";
}
