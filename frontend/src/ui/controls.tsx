import * as React from 'react';
import { AlertDialog } from '@base-ui/react/alert-dialog';
import { NumberField } from '@base-ui/react/number-field';
import { Select } from '@base-ui/react/select';
import { Slider } from '@base-ui/react/slider';
import { Switch } from '@base-ui/react/switch';
import { Toast } from '@base-ui/react/toast';
import { Tooltip } from '@base-ui/react/tooltip';
import { CaretUpDownIcon, CheckIcon, MinusIcon, PlusIcon } from './icons';
import styles from './ui.module.css';

export { styles as ui };

type ButtonProps = React.ComponentProps<'button'> & {
  variant?: 'default' | 'primary' | 'danger' | 'ghost';
  size?: 'default' | 'sm' | 'icon' | 'icon-sm';
};

export function Button({ variant = 'default', size = 'default', className, ...props }: ButtonProps) {
  return (
    <button
      type="button"
      className={[styles.Button, className].filter(Boolean).join(' ')}
      data-variant={variant}
      data-size={size}
      {...props}
    />
  );
}

export interface SelectOption {
  value: string;
  label: string;
  note?: string;
}

export function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
}) {
  return (
    <Select.Root
      items={options}
      value={value}
      onValueChange={(next) => {
        if (typeof next === 'string') onChange(next);
      }}
    >
      <Select.Label className={styles.Label}>{label}</Select.Label>
      <Select.Trigger className={styles.SelectTrigger}>
        <Select.Value className={styles.SelectValue} />
        <Select.Icon>
          <CaretUpDownIcon />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Positioner className={styles.Positioner} sideOffset={4}>
          <Select.Popup className={styles.SelectPopup}>
            <Select.List className={styles.SelectList}>
              {options.map((option) => (
                <Select.Item key={option.value} value={option.value} className={styles.SelectItem}>
                  <Select.ItemIndicator style={{ gridColumn: 1 }}>
                    <CheckIcon />
                  </Select.ItemIndicator>
                  <Select.ItemText style={{ gridColumn: 2 }}>{option.label}</Select.ItemText>
                  {option.note && <span className={styles.SelectItemNote}>{option.note}</span>}
                </Select.Item>
              ))}
            </Select.List>
          </Select.Popup>
        </Select.Positioner>
      </Select.Portal>
    </Select.Root>
  );
}

export function SliderField({
  label,
  value,
  min,
  max,
  step = 1,
  format = (v) => v.toLocaleString(),
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  format?: (value: number) => string;
  onChange: (value: number) => void;
}) {
  const id = React.useId();
  return (
    <Slider.Root
      className={styles.SliderField}
      value={value}
      min={min}
      max={max}
      step={step}
      onValueChange={(next) => onChange(Array.isArray(next) ? next[0] : next)}
    >
      <label className={styles.Label} htmlFor={id}>
        {label}
      </label>
      <span className={styles.SliderValue}>{format(value)}</span>
      <Slider.Control className={styles.SliderControl}>
        <Slider.Track className={styles.SliderTrack}>
          <Slider.Indicator className={styles.SliderIndicator} />
          <Slider.Thumb className={styles.SliderThumb} id={id} aria-label={label} />
        </Slider.Track>
      </Slider.Control>
    </Slider.Root>
  );
}

export function SwitchField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className={styles.SwitchLabel}>
      {label}
      <Switch.Root className={styles.Switch} checked={checked} onCheckedChange={onChange}>
        <Switch.Thumb className={styles.SwitchThumb} />
      </Switch.Root>
    </label>
  );
}

export function NumberInput({
  label,
  value,
  min,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  step: number;
  onChange: (value: number) => void;
}) {
  const id = React.useId();
  return (
    <NumberField.Root className={styles.NumberField} id={id} value={value} min={min} step={step} onValueChange={(v) => onChange(v ?? min)}>
      <label htmlFor={id} className={styles.Label}>
        {label}
      </label>
      <NumberField.Group className={styles.NumberGroup}>
        <NumberField.Decrement className={styles.NumberStep} aria-label="Decrease">
          <MinusIcon />
        </NumberField.Decrement>
        <NumberField.Input className={styles.NumberInput} />
        <NumberField.Increment className={styles.NumberStep} aria-label="Increase">
          <PlusIcon />
        </NumberField.Increment>
      </NumberField.Group>
    </NumberField.Root>
  );
}

export function Tip({ content, children }: { content: React.ReactNode; children: React.ReactElement }) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger render={children} />
      <Tooltip.Portal>
        <Tooltip.Positioner sideOffset={6} className={styles.Positioner}>
          <Tooltip.Popup className={styles.TooltipPopup}>{content}</Tooltip.Popup>
        </Tooltip.Positioner>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

export function Confirm({
  trigger,
  title,
  description,
  action,
  onConfirm,
}: {
  trigger: React.ReactElement;
  title: string;
  description: string;
  action: string;
  onConfirm: () => void;
}) {
  return (
    <AlertDialog.Root>
      <AlertDialog.Trigger render={trigger} />
      <AlertDialog.Portal>
        <AlertDialog.Backdrop className={styles.Backdrop} />
        <AlertDialog.Popup className={styles.DialogPopup}>
          <AlertDialog.Title className={styles.DialogTitle}>{title}</AlertDialog.Title>
          <AlertDialog.Description className={styles.DialogDescription}>{description}</AlertDialog.Description>
          <div className={styles.DialogActions}>
            <AlertDialog.Close render={<Button />}>Cancel</AlertDialog.Close>
            <AlertDialog.Close render={<Button variant="primary" />} onClick={onConfirm}>
              {action}
            </AlertDialog.Close>
          </div>
        </AlertDialog.Popup>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

export function Toasts() {
  const { toasts } = Toast.useToastManager();
  return (
    <Toast.Portal>
      <Toast.Viewport className={styles.ToastViewport}>
        {toasts.map((toast) => (
          <Toast.Root key={toast.id} toast={toast} className={styles.Toast}>
            <Toast.Content className={styles.ToastContent}>
              <div className={styles.ToastText}>
                <Toast.Title className={styles.ToastTitle} />
                <Toast.Description className={styles.ToastDescription} />
              </div>
              <Toast.Close render={<Button size="sm" variant="ghost" />}>Dismiss</Toast.Close>
            </Toast.Content>
          </Toast.Root>
        ))}
      </Toast.Viewport>
    </Toast.Portal>
  );
}
