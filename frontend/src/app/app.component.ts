import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBarModule } from '@angular/material/snack-bar';
import { NetworkCardComponent } from './components/network-card/network-card.component';
import { WilabApiService } from './services/wilab-api.service';
import { InterfaceInfo } from './models/network.models';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    CommonModule,
    MatToolbarModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
    NetworkCardComponent
  ],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent implements OnInit {
  title = 'Wi-Lab Network Management';
  interfaces: InterfaceInfo[] = [];
  loading = true;
  error: string | null = null;

  constructor(private apiService: WilabApiService) {}

  public ngOnInit() {
    this.loadInterfaces();
  }

  public loadInterfaces() {
    this.loading = true;
    this.error = null;
    this.apiService.getInterfaces().subscribe({
      next: (interfaces) => {
        this.interfaces = interfaces;
        this.loading = false;
      },
      error: (err) => {
        this.error = `Failed to load interfaces: ${err.message}`;
        this.loading = false;
        console.error('Error loading interfaces:', err);
      }
    });
  }
}
