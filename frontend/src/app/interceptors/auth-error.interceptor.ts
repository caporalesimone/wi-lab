import { HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { tap } from 'rxjs/operators';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { AuthService } from '../services/auth.service';
import { TokenDialogComponent } from '../components/token-dialog/token-dialog.component';

let dialogOpen = false;

export const authErrorInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService);
  const dialog = inject(MatDialog);
  const snackBar = inject(MatSnackBar);

  return next(req).pipe(
    tap({
      error: (err: HttpErrorResponse) => {
        if (err.status === 401 && !dialogOpen) {
          dialogOpen = true;
          authService.clearToken();
          snackBar.open('Invalid or expired token', 'Close', { duration: 4000 });

          const dialogRef = dialog.open(TokenDialogComponent, {
            width: '450px',
            disableClose: true,
            data: { required: true }
          });

          dialogRef.afterClosed().subscribe((token: string | null) => {
            dialogOpen = false;
            if (token) {
              authService.setToken(token);
            }
          });
        }
      }
    })
  );
};
