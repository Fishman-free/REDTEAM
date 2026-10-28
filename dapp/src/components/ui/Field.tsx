import {
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

interface FieldShellProps {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  htmlFor?: string;
  className?: string;
  children: ReactNode;
  aside?: ReactNode;
}

export function Field({
  label,
  hint,
  error,
  required,
  htmlFor,
  className = "",
  children,
  aside,
}: FieldShellProps) {
  return (
    <div className={`field ${className}`.trim()}>
      <div className="field__label-row">
        <label className="field__label" htmlFor={htmlFor}>
          {label}
          {required && <span className="field__required">*</span>}
        </label>
        {aside && <span className="field__aside">{aside}</span>}
      </div>
      {children}
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : (
        hint && <p className="field__hint">{hint}</p>
      )}
    </div>
  );
}

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  suffix?: ReactNode;
  aside?: ReactNode;
}

export function TextField({
  label,
  hint,
  error,
  suffix,
  aside,
  className = "",
  id,
  required,
  ...props
}: TextFieldProps) {
  const generated = useId();
  const inputId = id || generated;
  return (
    <Field
      label={label}
      hint={hint}
      error={error}
      required={required}
      htmlFor={inputId}
      aside={aside}
      className={className}
    >
      <div className={`field__control ${suffix ? "field__control--suffix" : ""}`.trim()}>
        <input
          id={inputId}
          className="input"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${inputId}-error` : undefined}
          required={required}
          {...props}
        />
        {suffix && <span className="field__suffix">{suffix}</span>}
      </div>
    </Field>
  );
}

interface TextAreaFieldProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  counter?: boolean;
  aside?: ReactNode;
}

export function TextAreaField({
  label,
  hint,
  error,
  counter = false,
  aside,
  className = "",
  id,
  required,
  value,
  maxLength,
  ...props
}: TextAreaFieldProps) {
  const generated = useId();
  const inputId = id || generated;
  const length = typeof value === "string" ? value.length : 0;
  return (
    <Field
      label={label}
      hint={hint}
      error={error}
      required={required}
      htmlFor={inputId}
      aside={
        aside ??
        (counter && maxLength ? (
          <span className={length > maxLength * 0.9 ? "is-warning" : ""}>
            {length} / {maxLength}
          </span>
        ) : undefined)
      }
      className={className}
    >
      <textarea
        id={inputId}
        className="textarea"
        value={value}
        maxLength={maxLength}
        aria-invalid={error ? true : undefined}
        required={required}
        {...props}
      />
    </Field>
  );
}

interface SelectOption {
  value: string;
  label: string;
}

interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  options: SelectOption[];
  placeholder?: string;
  aside?: ReactNode;
}

export function SelectField({
  label,
  hint,
  error,
  options,
  placeholder,
  aside,
  className = "",
  id,
  required,
  ...props
}: SelectFieldProps) {
  const generated = useId();
  const inputId = id || generated;
  return (
    <Field
      label={label}
      hint={hint}
      error={error}
      required={required}
      htmlFor={inputId}
      aside={aside}
      className={className}
    >
      <div className="field__control field__control--select">
        <select id={inputId} className="select" required={required} {...props}>
          {placeholder && <option value="">{placeholder}</option>}
          {options.map((option) => (
            <option value={option.value} key={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
    </Field>
  );
}

interface CheckboxFieldProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
  description?: ReactNode;
  tone?: "default" | "danger";
  disabled?: boolean;
  className?: string;
}

export function CheckboxField({
  checked,
  onChange,
  children,
  description,
  tone = "default",
  disabled,
  className = "",
}: CheckboxFieldProps) {
  return (
    <label className={`check check--${tone} ${className}`.trim()}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        disabled={disabled}
      />
      <span className="check__body">
        <span className="check__label">{children}</span>
        {description && <span className="check__description">{description}</span>}
      </span>
    </label>
  );
}
