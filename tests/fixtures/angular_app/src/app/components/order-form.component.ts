import { Component } from '@angular/core';

@Component({
  selector: 'app-order-form',
  templateUrl: './order-form.component.html'
})
export class OrderFormComponent {
  statusOptions = [
    { label: 'Draft', value: 'DRAFT' },
    { label: 'Published', value: 'PUBLISHED' },
    { label: 'Archived', value: 'ARCHIVED' }
  ];

  adTypeOptions = ['Radio', 'Digital', 'Video'];

  serviceOptions = [
    { name: 'Mixing', code: 'MIX' },
    { name: 'Voiceover', code: 'VO' }
  ];
}
