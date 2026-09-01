import { ConstraintEntryScreen } from "../../../../components/screens/full-ui-workflows";

type PageProps = {
  params: Promise<{ productionId: string }>;
  searchParams?: Promise<{ boardId?: string | string[] }>;
};

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ConstraintEntryPage({
  params,
  searchParams,
}: PageProps) {
  const { productionId } = await params;
  const query = searchParams ? await searchParams : {};
  return (
    <ConstraintEntryScreen
      productionId={productionId}
      boardId={firstParam(query.boardId)}
    />
  );
}
