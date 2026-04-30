interface Props {
  steps: string[];
}

export function RecipeSteps({ steps }: Props) {
  return (
    <ol style={{ marginTop: "0.25rem", paddingLeft: "1.25rem" }}>
      {steps.map((step, i) => (
        <li key={i} style={{ marginBottom: "0.4rem", lineHeight: 1.45 }}>
          {step}
        </li>
      ))}
    </ol>
  );
}
