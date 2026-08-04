import { useSearchParams } from 'react-router-dom';

import ProviderWorkbenchPage from './ProviderWorkbenchPage';
import ServiceOrderWorkbenchPage from './ServiceOrderWorkbenchPage';

export default function ProviderWorkspacePage() {
  const [searchParams] = useSearchParams();
  return searchParams.get('view') === 'workbench'
    ? <ServiceOrderWorkbenchPage />
    : <ProviderWorkbenchPage />;
}
