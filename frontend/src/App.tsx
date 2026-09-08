import { RouterProvider } from 'react-router-dom';
import { AuthProvider } from './auth/AuthProvider';
import { ProductProvider } from './context/ProductContext';
import { router } from './router';

function App() {
  return (
    <AuthProvider>
      <ProductProvider>
        <RouterProvider router={router} />
      </ProductProvider>
    </AuthProvider>
  );
}

export default App;
