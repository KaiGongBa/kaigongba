import { useCallback, useEffect, useState } from 'react';

export type MarketplaceResourceState<T> = {
  data: T | null;
  loading: boolean;
  error: string;
  reload: () => void;
};

export function useMarketplaceResource<T>(
  loader: () => Promise<T>,
  dependencyKey: string,
): MarketplaceResourceState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    void loader()
      .then((result) => {
        if (active) setData(result);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setData(null);
        setError(reason instanceof Error ? reason.message : '数据加载失败');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [dependencyKey, revision]);

  const reload = useCallback(() => setRevision((value) => value + 1), []);
  return { data, loading, error, reload };
}
