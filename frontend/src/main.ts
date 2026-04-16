import { bootstrapApplication } from '@angular/platform-browser';
import { provideAnimations } from '@angular/platform-browser/animations';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { AppComponent } from './app/app.component';
import { appConfig } from './app/app.config';
import { authErrorInterceptor } from './app/interceptors/auth-error.interceptor';

bootstrapApplication(AppComponent, {
  ...appConfig,
  providers: [
    ...appConfig.providers || [],
    provideAnimations(),
    provideHttpClient(withInterceptors([authErrorInterceptor]))
  ]
}).catch(err => console.error(err));
