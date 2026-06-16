import type {EdgeType, ObservationType, RegistryValue} from "./types/entities";

export type SelectOption = {
  value: string;
  label: string;
};

export function registryOptions(items: RegistryValue[]): SelectOption[] {
  return items
    .filter((item) => item.is_active !== false)
    .map((item) => ({value: item.value, label: item.label || item.value}));
}

export function edgeTypeOptions(items: EdgeType[]): SelectOption[] {
  return items
    .filter((item) => item.active !== false)
    .map((item) => ({value: item.relation_type, label: item.description || item.relation_type}));
}

export function observationTypeOptions(items: ObservationType[]): SelectOption[] {
  return items
    .filter((item) => item.active !== false)
    .map((item) => ({value: item.observation_type, label: item.description || item.observation_type}));
}

export function includeAllOption(options: SelectOption[]): SelectOption[] {
  return [{value: "all", label: "all"}, ...options];
}

export function optionsWithCurrent(options: SelectOption[], current: string): SelectOption[] {
  if (!current || options.some((option) => option.value === current)) {
    return options;
  }
  return [{value: current, label: current}, ...options];
}

export function normalizeOptionValue(current: string, options: SelectOption[]) {
  if (!options.length || options.some((option) => option.value === current)) {
    return current;
  }
  return options[0].value;
}
