/*==============================================================================

  Copyright (c) Kitware, Inc.

  See http://www.slicer.org/copyright/copyright.txt for details.

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  This file was originally developed by Julien Finet, Kitware, Inc.
  and was partially funded by NIH grant 3P41RR013218-12S1

==============================================================================*/

#ifndef __qNewMPR2SlicerAppMainWindow_p_h
#define __qNewMPR2SlicerAppMainWindow_p_h

// NewMPR2Slicer includes
#include "qNewMPR2SlicerAppMainWindow.h"

// Slicer includes
#include "qSlicerMainWindow_p.h"

// Qt includes
#include <QRect>

//-----------------------------------------------------------------------------
class Q_NEWMPR2SLICER_APP_EXPORT qNewMPR2SlicerAppMainWindowPrivate
  : public qSlicerMainWindowPrivate
{
  Q_DECLARE_PUBLIC(qNewMPR2SlicerAppMainWindow);
public:
  typedef qSlicerMainWindowPrivate Superclass;
  qNewMPR2SlicerAppMainWindowPrivate(qNewMPR2SlicerAppMainWindow& object);
  virtual ~qNewMPR2SlicerAppMainWindowPrivate();

  virtual void init();
  /// Reimplemented for custom behavior
  virtual void setupUi(QMainWindow * mainWindow);
};

#endif
